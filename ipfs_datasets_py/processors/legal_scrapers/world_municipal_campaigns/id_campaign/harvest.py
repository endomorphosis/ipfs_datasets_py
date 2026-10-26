"""Indonesia tranche-1 campaign harvester.

Harvests Perda for registry units whose portals fit the pilot template
family or a small variant discovered by fit-test + census probing
(2026-10-12). Reuses the pilot pipeline (id_pilot/id_pilot_build.py)
primitives: PoliteSession, pdf_text, split_pasal, text_to_html, plus
world_municipal normalization + fail-closed validation.

Modes:
  enum     — enumerate candidates per unit only (no PDF fetches)
  harvest  — full pipeline: enumerate, cap, fetch, build, validate, stage
State: id_campaign_tranche1_state.json (per-BPS status), resumable.
"""
import importlib.util
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup

WS = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
CAMP = WS / "id_campaign"
STAGE = CAMP / "staging"
STAGE.mkdir(parents=True, exist_ok=True)
STATE_PATH = CAMP / "id_campaign_tranche1_state.json"
RETRIEVED = "2026-10-12"

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

spec = importlib.util.spec_from_file_location("id_pilot_build", Path(__file__).resolve().parent.parent / "id_pilot" / "id_pilot_build.py")  # repo snapshot #3/#6: sibling pilot dir (was WS / "id_pilot", an absolute hidden_files path)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)
PoliteSession, pdf_text, split_pasal = pilot.PoliteSession, pilot.pdf_text, pilot.split_pasal
text_to_html, parse_id_date, slug = pilot.text_to_html, pilot.parse_id_date, pilot.slug

BPS_SCHEME = get_scheme("ID")
MAX_PDF_BYTES = pilot.MAX_PDF_BYTES

# ---------------------------------------------------------------- unit table
# (bps, registry name, host, adapter)
UNITS = [
    ("3210", "Kabupaten Majalengka", "jdih.majalengkakab.go.id", "common_dokumen"),
    ("3604", "Kabupaten Serang", "jdih.serangkab.go.id", "common_dokumen"),
    ("9104", "Kabupaten Teluk Bintuni", "jdih.telukbintunikab.go.id", "common_dokumen"),
    ("3602", "Kabupaten Lebak", "jdih.lebakkab.go.id", "common_dokumen"),
    ("3373", "Kota Salatiga", "jdih.salatiga.go.id", "common_dokumen"),
    ("3306", "Kabupaten Purworejo", "jdih.purworejokab.go.id", "inventarisasi"),
    ("3317", "Kabupaten Rembang", "jdih.rembangkab.go.id", "inventarisasi"),
    ("3320", "Kabupaten Jepara", "jdih.jepara.go.id", "inventarisasi"),
    ("3504", "Kabupaten Tulungagung", "jdih.tulungagung.go.id", "tulungagung"),
    ("3518", "Kabupaten Nganjuk", "jdih.nganjukkab.go.id", "nganjuk"),
    ("5202", "Kabupaten Lombok Tengah", "jdih.lomboktengahkab.go.id", "lomboktengah"),
    ("1807", "Kabupaten Way Kanan", "jdih.waykanankab.go.id", "waykanan"),
    ("7203", "Kabupaten Morowali", "jdih.morowalikab.go.id", "morowali"),
    ("6371", "Kota Banjarmasin", "jdih.banjarmasinkota.go.id", "banjarmasin"),
    ("6303", "Kabupaten Banjar", "jdih.banjarkab.go.id", "banjar"),
    ("3521", "Kabupaten Ngawi", "jdih.ngawikab.go.id", "ngawi"),
    ("6108", "Kabupaten Kapuas Hulu", "jdih.kapuashulukab.go.id", "kapuashulu"),
    ("6103", "Kabupaten Landak", "jdih.landakkab.go.id", "kapuashulu"),
    ("8105", "Kabupaten Kepulauan Aru", "jdih.kepulauanarukab.go.id", "aru"),
    ("7372", "Kota Parepare", "jdih.pareparekota.go.id", "parepare"),
    ("3311", "Kabupaten Sukoharjo", "jdih.sukoharjokab.go.id", "sukoharjo"),
    ("6401", "Kabupaten Paser", "jdih.paserkab.go.id", "dokumen_view"),
    ("9403", "Kabupaten Jayapura", "jdih.jayapurakab.go.id", "dokumen_view_jayapura"),
    ("3401", "Kabupaten Kulon Progo", "jdih.kulonprogokab.go.id", "kulonprogo"),
]
GENERIC_UNITS = [
    ("1671", "Kota Palembang", "jdih.palembang.go.id"),
    ("3209", "Kabupaten Cirebon", "jdih.cirebonkab.go.id"),
    ("3310", "Kabupaten Klaten", "jdih.klaten.go.id"),
    ("3524", "Kabupaten Lamongan", "jdih.lamongankab.go.id"),
    ("6404", "Kabupaten Kutai Timur", "jdih.kutaitimurkab.go.id"),
]
PRESKIP = {
    "1307": ("Kabupaten Agam", "jdih.agamkab.go.id",
             "listing is AJAX/POST-driven (web2/ajax/peraturan expects search "
             "params); not enumerable with GET adapters — tranche 2"),
    "3204": ("Kabupaten Bandung", "jdih.bandungkab.go.id",
             "registry host collided with Kota Bandung's portal; own portal "
             "confirmed but its kategori listing is JS-populated (rows built "
             "client-side, data endpoint not exposed in page source) — tranche 2"),
    "3576": ("Kota Mojokerto", "jdih.mojokertokota.go.id",
             "host timed out repeatedly; homepage is a general law-office site "
             "with no enumerable Perda listing"),
    "6309": ("Kabupaten Tabalong", "jdih.tabalongkab.go.id",
             "homepage is a JS shell with no server-side links; no enumerable listing"),
}

LIST_URLS = {
    "common_dokumen": {
        "3210": "/dokumen?tipe_dokumen=1", "3604": "/dokumen?tipe_dokumen=1",
        "9104": "/dokumen?tipe_dokumen=1", "3602": "/dokumen/perda",
        "3373": "/dokumen/peraturan",
    },
}

CAP_FULL = 150          # take whole catalog at or below this
CAP_RECENT_YEAR = 2020  # else restrict to this year and later
CAP_HARD = 250          # absolute per-unit doc cap after year restriction
GENERIC_CAP = 60

_state_lock = threading.Lock()


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state):
    with _state_lock:
        STATE_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False))


# ---------------------------------------------------------------- helpers

def clean_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def nomor_tahun(text):
    m = re.search(r"Nomor\s+(\d+)\s+Tahun\s+(\d{4})", text or "", re.I)
    return (m.group(1), m.group(2)) if m else ("", "")


def head_reg_type(title):
    """The regulation type a title *heads* with: the first 'Peraturan X'
    mention decides (a Perwali implementing a Perda is not a Perda)."""
    m = re.search(r"peraturan\s+(daerah|wali\s?kota|bupati|gubernur|kepala)",
                  (title or "").lower())
    return m.group(1) if m else ""


def is_perda_title(text):
    t = (text or "").lower()
    if "peraturan daerah" not in t:
        return False
    if head_reg_type(text) not in ("daerah",):
        return False
    if re.search(r"ranperda|rancangan peraturan daerah|naskah akademik|abstrak|abstak", t):
        return False
    return True


def is_qanun_title(text):
    """Aceh's Perda-equivalent instruments head with 'Qanun'
    (Qanun Kabupaten/Kota). Eligible ONLY on units flagged
    qanun_equivalent (Aceh dih-family hosts) under Benjamin's
    2026-10-13 policy decision."""
    t = (text or "").lower()
    if not re.match(r"\s*qanun\b", t):
        return False
    if re.search(r"rancangan qanun|ranqanun|naskah akademik|abstrak|abstak", t):
        return False
    return True


def pdf_head_reg_type(text):
    """Regulation type from the document's own head (first ~1500 chars)."""
    head = clean_ws(text[:1500]).upper()
    m = re.search(r"PERATURAN\s+(DAERAH|WALIKOTA|WALI KOTA|BUPATI|GUBERNUR)", head)
    return m.group(1) if m else ""


def robots_blocked(sess, base, needed_prefixes):
    """Live robots check: True if a plain UA-* Disallow prefix blocks a
    needed path. Wildcard/query rules are ignored (spam filters)."""
    try:
        r = sess.get(base + "/robots.txt", timeout=45)
        if r.status_code != 200:
            return False
        ua_star, rules = False, []
        for line in r.text.splitlines():
            line = line.strip()
            if line.lower().startswith("user-agent:"):
                ua_star = line.split(":", 1)[1].strip() == "*"
            elif ua_star and line.lower().startswith("disallow:"):
                p = line.split(":", 1)[1].strip()
                if p and "*" not in p and "?" not in p:
                    rules.append(p)
        for p in rules:
            if p == "/":
                return True
            for need in needed_prefixes:
                if need.startswith(p):
                    return True
        return False
    except Exception:
        return False


def paginate(sess, first_url, extract, max_pages=60, page_param="page", timeout=240):
    """Fetch first_url then first_url&page=2.. until extract yields no new
    keys. extract(html, url) -> dict key->candidate."""
    seen = {}
    url = first_url
    for page in range(1, max_pages + 1):
        if page > 1:
            sep = "&" if "?" in first_url else "?"
            url = f"{first_url}{sep}{page_param}={page}"
        r = sess.get(url, timeout=timeout)
        if r.status_code != 200:
            break
        new = extract(r.text, url)
        fresh = {k: v for k, v in new.items() if k not in seen}
        seen.update(new)
        if not fresh:
            break
    return seen


def card_text(anchor, max_len=900):
    """Climb ancestors; return the SMALLEST ancestor text that names the
    document (contains 'Peraturan' or 'Nomor'), else the anchor text.
    Stops at the first match so sibling documents never bleed in."""
    node = anchor
    own = anchor.get_text(" ", strip=True)
    for _ in range(5):
        node = node.parent
        if node is None:
            break
        t = clean_ws(node.get_text(" ", strip=True))
        if len(t) > max_len:
            break
        if "Peraturan" in t or "Nomor" in t:
            return t
    return own


def pdf_head_title(text):
    """Extract a full Perda title from the head of the extracted PDF text
    (fallback when listings carry no usable title)."""
    head = clean_ws(text[:3000])
    m = re.search(
        r"PERATURAN DAERAH(?:\s+(?:KABUPATEN|KOTA)\s+[A-Z][A-Z .'\-]+?)?"
        r"\s+NOMOR\s+(\d+)\s+TAHUN\s+(\d{4})\s+TENTANG\s+([^:]{8,220}?)"
        r"(?:\s+(?:DENGAN RAHMAT|MENIMBANG|MENGINGAT)|$)",
        head)
    if not m:
        return ""
    t = f"Peraturan Daerah Nomor {m.group(1)} Tahun {m.group(2)} Tentang {m.group(3).title()}"
    return clean_ws(t)


def find_pdf_in_detail(html, page_url):
    """Score PDF-ish links on a detail page; return best absolute URL."""
    soup = BeautifulSoup(html, "html.parser")
    scored = []
    for a in soup.find_all("a", href=True):
        h = urljoin(page_url, a["href"])
        low = h.lower()
        if not (low.split("?")[0].endswith(".pdf") or "download" in low
                or "get_file" in low or "/berkas/" in low or "unduh" in low):
            continue
        score = 0
        if "perda" in low:
            score += 3
        if re.search(r"abstrak|abstak|naskah|ranperda", low):
            score -= 4
        if low.split("?")[0].endswith(".pdf"):
            score += 2
        scored.append((score, h))
    if not scored:
        return ""
    scored.sort(reverse=True)
    return scored[0][1]

# ---------------------------------------------------------------- adapters
# Each returns dict key -> candidate(detail_url, pdf_url, title, nomor, tahun, key)

def enum_common_dokumen(sess, base, unit):
    bps = unit["bps"]
    configured = LIST_URLS["common_dokumen"][bps]
    fallbacks = ["/dokumen/perda", "/dokumen/peraturan", "/dokumen?tipe_dokumen=1"]
    list_paths = []
    for p in [configured] + fallbacks:
        if p not in list_paths:
            list_paths.append(p)
    if bps == "3373":  # Salatiga: generic listing is latest-docs only; perda route first
        list_paths.sort(key=lambda p: 0 if p == "/dokumen/perda" else 1)

    def make_extract():
        def extract(html, url):
            soup = BeautifulSoup(html, "html.parser")
            out = {}
            for a in soup.find_all("a", href=re.compile(r"\.pdf$", re.I)):
                href = urljoin(url, a["href"])
                fname = urlparse(href).path.rsplit("/", 1)[-1]
                teu = re.match(r"(\d{4})pd(\d{4})(\d+)\.pdf$", fname, re.I)
                prd = re.match(r"(\d{4})prd(\d{4})(\d+)\.pdf$", fname, re.I)
                card = card_text(a)
                nomor = tahun = ""
                if teu:  # host's own portal; middle digits may be a TEU code
                    nomor, tahun = str(int(teu.group(3))), teu.group(1)
                elif prd:  # Teluk Bintuni naming: <code>prd<year><num>.pdf
                    nomor, tahun = str(int(prd.group(3))), prd.group(2)
                elif is_perda_title(card) or re.match(r"Perda[ _]", fname, re.I):
                    nomor, tahun = nomor_tahun(card)
                    if not nomor:
                        nomor, tahun = nomor_tahun(fname.replace("_", " "))
                    m = re.match(r"Perda[ _](\d{4})[ _](\d+)", fname, re.I)
                    if m:
                        tahun, nomor = m.group(1), m.group(2)
                else:
                    continue
                title = card if is_perda_title(card) else ""
                if title:
                    title = re.split(r"\s+(Berlaku|Tidak Berlaku|Status|Download|Detail)\b",
                                     title)[0].strip()
                out[href] = dict(detail_url=url, pdf_url=href, title=title,
                                 nomor=nomor, tahun=tahun, key=fname)
            return out
        return extract

    for path in list_paths:
        cands = paginate(sess, base + path, make_extract())
        if cands:
            return cands
    return {}


def _detail_enum(sess, first_url, detail_re, title_from="anchor", max_pages=60):
    def extract(html, url):
        soup = BeautifulSoup(html, "html.parser")
        out = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if not re.search(detail_re, href):
                continue
            txt = clean_ws(a.get_text(" ", strip=True))
            if a.get("href") in out:
                continue
            prev = out.get(href, {})
            title = txt if (txt and len(txt) > len(prev.get("title", ""))) else prev.get("title", "")
            out[href] = dict(detail_url=href, pdf_url="",
                             title=title if title_from == "anchor" else "",
                             nomor="", tahun="", key=href.rstrip("/").split("/")[-1])
        return out

    return paginate(sess, first_url, extract, max_pages=max_pages)


def enum_inventarisasi(sess, base, unit):
    cands = _detail_enum(sess, base + "/inventarisasi-hukum/kategori/peraturan-daerah",
                         r"/inventarisasi-hukum/detail/perda_")
    for c in cands.values():
        m = re.search(r"perda_(\d+)_th_(\d{4})", c["detail_url"])
        if m:
            c["nomor"], c["tahun"] = m.group(1), m.group(2)
        if not c["title"]:
            n, t = nomor_tahun(c["detail_url"])
            c["title"] = ""
    return cands


def enum_tulungagung(sess, base, unit):
    cands = _detail_enum(sess, base + "/peraturan?searchJenisPerda=1",
                         r"/peraturan/\d+$")
    for c in cands.values():
        c["nomor"], c["tahun"] = nomor_tahun(c["title"])
    return {k: v for k, v in cands.items() if is_perda_title(v["title"]) or v["nomor"]}


def enum_nganjuk(sess, base, unit):
    def extract(html, url):
        soup = BeautifulSoup(html, "html.parser")
        out = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            m = re.search(r"/prokum/get_file\?id_prokum=([A-Za-z0-9+/=]+)", href)
            if not m:
                continue
            pid = m.group(1)
            card = card_text(a)
            nomor, tahun = nomor_tahun(card)
            tm = re.search(r"(Peraturan Daerah[^•|]{0,200})", card)
            title = clean_ws(tm.group(1)) if tm else card
            out[pid] = dict(
                detail_url=f"{base}/prokum/detail?id_kategori=MQ==&id_prokum={pid}",
                pdf_url=href, title=title, nomor=nomor, tahun=tahun, key=pid)
        return out

    return paginate(sess, base + "/prokum?id_kategori=MQ==", extract)


def enum_lomboktengah(sess, base, unit):
    cands = _detail_enum(sess, base + "/home/kategori/peraturan-daerah",
                         r"/home/detail-produk-hukum/\d+$")
    for c in cands.values():
        c["nomor"], c["tahun"] = nomor_tahun(c["title"])
    return cands


def enum_waykanan(sess, base, unit):
    first = (base + "/dokumen.php?cari=&kat=2&jenis=14&kec=&kel=&tahun=&status=")

    def extract(html, url):
        soup = BeautifulSoup(html, "html.parser")
        out = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if "dokumen_view.php" not in href:
                continue
            row = card_text(a, max_len=1200)
            out[href] = dict(detail_url=href, pdf_url="", title=row,
                             nomor="", tahun="", key=href[-24:])
        return out

    return paginate(sess, first, extract)


def enum_morowali(sess, base, unit):
    return _detail_enum(sess, base + "/dokumen?kategori=Peraturan&tipe_singkatan=Perda",
                        r"/dokumen/\d+$")


def enum_banjarmasin(sess, base, unit):
    def extract(html, url):
        soup = BeautifulSoup(html, "html.parser")
        out = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            m = re.search(r"/produkHukum/download/(\d+)$", href)
            if not m:
                continue
            row = card_text(a, max_len=2000)
            if not is_perda_title(row):
                continue
            nomor, tahun = nomor_tahun(row)
            out[m.group(1)] = dict(
                detail_url=f"{base}/produkHukum/detail-produk-hukum/{m.group(1)}",
                pdf_url=href, title=row, nomor=nomor, tahun=tahun, key=m.group(1))
        return out

    return paginate(sess, base + "/produkHukum?tipe_dokumen=1", extract)


def enum_banjar(sess, base, unit):
    first = (base + "/pencarian?q=&jenis_peraturan=56&urusan_pemerintahan="
             "&nomor_peraturan=&tahun_terbit=")
    cands = _detail_enum(sess, first, r"/pencarian/\d+/detail$")
    for c in cands.values():
        c["title"] = c["title"].title() if c["title"].isupper() else c["title"]
        c["nomor"], c["tahun"] = nomor_tahun(c["title"])
    return cands


def enum_ngawi(sess, base, unit):
    r = sess.get(base + "/peraturan/1", timeout=150)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        m = re.search(r"/peraturan/download/(\d+)$", href)
        if not m:
            continue
        row = card_text(a, max_len=1200)
        nomor, tahun = nomor_tahun(row)
        out[m.group(1)] = dict(detail_url=f"{base}/peraturan/view/{m.group(1)}",
                               pdf_url=href, title=row, nomor=nomor,
                               tahun=tahun, key=m.group(1))
    return out


def enum_kapuashulu(sess, base, unit):
    if unit["bps"] == "6103":  # Landak: same permalinks, search listing instead
        def extract_landak(html, url):
            soup = BeautifulSoup(html, "html.parser")
            out = {}
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a["href"])
                m = re.search(r"/peraturan/(\d{4})perda(\d+)/?$", href, re.I)
                if not m:
                    continue
                txt = clean_ws(a.get_text(" ", strip=True))
                out[href] = dict(detail_url=href, pdf_url="", title=txt,
                                 nomor=str(int(m.group(2))), tahun=m.group(1),
                                 key=href.rstrip("/").split("/")[-1],
                                 unduh_url=f"{base}/unduh/{href.rstrip('/').split('/')[-1]}/")
            return out

        return paginate(sess, base + "/cari/?jenisperaturan=2", extract_landak)
    list_url = base + "/peraturan/jenis/perda/"
    r = sess.get(list_url, timeout=150)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(list_url, a["href"])
        m = re.search(r"/peraturan/(\d{4})perda(\d+)/?$", href, re.I)
        if not m:
            continue
        txt = clean_ws(a.get_text(" ", strip=True))
        slug_part = href.rstrip("/").split("/")[-1]
        out[href] = dict(detail_url=href, pdf_url="", title=txt,
                         nomor=str(int(m.group(2))), tahun=m.group(1),
                         key=slug_part,
                         unduh_url=f"{base}/unduh/{slug_part}/")
    return out


def enum_aru(sess, base, unit):
    first = base + "/peraturan/daftar?id=32bb90e8976aab5298d5da10fe66f21d"
    cands = _detail_enum(sess, first, r"/peraturan/lihat/[^/]+$")
    for c in cands.values():
        c["nomor"], c["tahun"] = nomor_tahun(c["title"])
    return cands


def enum_parepare(sess, base, unit):
    seen = {}
    url = base + "/category/semua-peraturan/peraturan_daerah"
    for page in range(1, 41):
        u = url if page == 1 else f"{url}/page/{page}"
        r = sess.get(u, timeout=150)
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        fresh = 0
        for a in soup.find_all("a", href=True):
            href = urljoin(u, a["href"])
            m = re.search(r"/\d{4}/\d{2}/peraturan-daerah[^/]*$", href)
            if not m or href in seen:
                continue
            slug_txt = href.rstrip("/").split("/")[-1].replace("-", " ")
            nomor, tahun = nomor_tahun(slug_txt)
            seen[href] = dict(detail_url=href, pdf_url="", title=slug_txt,
                              nomor=nomor, tahun=tahun,
                              key=href.rstrip("/").split("/")[-1])
            fresh += 1
        if not fresh:
            break
    return seen


def enum_sukoharjo(sess, base, unit):
    cands = _detail_enum(sess, base + "/produk", r"/produk/detail/\d+$")
    keep = {}
    for k, v in cands.items():
        if is_perda_title(v["title"]):
            v["nomor"], v["tahun"] = nomor_tahun(v["title"])
            keep[k] = v
    return keep


def enum_dokumen_view(sess, base, unit):
    return _detail_enum(sess, base + "/dokumen/peraturan", r"/dokumen/view\?id=\d+")


def enum_jayapura(sess, base, unit):
    """Jayapura's /dokumen/peraturan is a type index; pick the DokumenSearch
    link labeled Peraturan Daerah, else probe index tipe values 1..4."""
    r = sess.get(base + "/dokumen/peraturan", timeout=240)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    listing = ""
    for a in soup.find_all("a", href=True):
        if "DokumenSearch" not in a["href"]:
            continue
        if "peraturan daerah" in clean_ws(a.get_text(" ", strip=True)).lower():
            listing = urljoin(base, a["href"])
            break
    if not listing:
        for t in (1, 2, 3, 4):
            u = (base + "/dokumen/index?DokumenSearch%5Btipe_dokumen%5D=" + str(t))
            rr = sess.get(u, timeout=120)
            if rr.status_code == 200 and "PERATURAN DAERAH" in rr.text:
                listing = u
                break
    if not listing:
        return {}
    return _detail_enum(sess, listing, r"/dokumen/view\?id=\d+")


def enum_kulonprogo(sess, base, unit):
    def extract(html, url):
        soup = BeautifulSoup(html, "html.parser")
        out = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            m = re.search(r"/peraturan/(\d+)/([^/]+\.pdf)$", href, re.I)
            if m:
                row = card_text(a, max_len=1200)
                nomor, tahun = nomor_tahun(row)
                out[m.group(1)] = dict(detail_url=f"{base}/detail/{m.group(1)}",
                                       pdf_url=href, title=row, nomor=nomor,
                                       tahun=tahun, key=m.group(1))
                continue
            m = re.search(r"/detail/(\d+)$", href)
            if m and "peraturan daerah" in clean_ws(a.get_text(" ", strip=True)).lower():
                out.setdefault(m.group(1), dict(
                    detail_url=href, pdf_url="", title=clean_ws(a.get_text(" ", strip=True)),
                    nomor="", tahun="", key=m.group(1)))
        return out

    return paginate(sess, base + "/pencarian?jenis=1", extract)


ENUMERATORS = {
    "common_dokumen": enum_common_dokumen,
    "inventarisasi": enum_inventarisasi,
    "tulungagung": enum_tulungagung,
    "nganjuk": enum_nganjuk,
    "lomboktengah": enum_lomboktengah,
    "waykanan": enum_waykanan,
    "morowali": enum_morowali,
    "banjarmasin": enum_banjarmasin,
    "banjar": enum_banjar,
    "ngawi": enum_ngawi,
    "kapuashulu": enum_kapuashulu,
    "aru": enum_aru,
    "parepare": enum_parepare,
    "sukoharjo": enum_sukoharjo,
    "dokumen_view": enum_dokumen_view,
    "dokumen_view_jayapura": enum_jayapura,
    "kulonprogo": enum_kulonprogo,
}

RESOLVER_ADAPTERS = {"inventarisasi", "tulungagung", "lomboktengah", "waykanan",
                     "morowali", "banjar", "kapuashulu", "aru", "parepare",
                     "sukoharjo", "dokumen_view", "dokumen_view_jayapura"}


def resolve_pdf(sess, cand):
    """Fetch the detail page; fill pdf_url + better title + date if present."""
    if cand.get("unduh_url"):
        # Kapuas Hulu / Landak CMS: JSON counter endpoint returns the file
        r = sess.get(cand["unduh_url"], timeout=120)
        r.raise_for_status()
        try:
            data = r.json()
            if data.get("file"):
                cand["pdf_url"] = urljoin(cand["detail_url"], data["file"])
        except ValueError:
            pass
    r = sess.get(cand["detail_url"], timeout=150)
    r.raise_for_status()
    if not cand.get("pdf_url"):
        cand["pdf_url"] = find_pdf_in_detail(r.text, cand["detail_url"])
    plain = BeautifulSoup(r.text, "html.parser").get_text(" ")
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

# ---------------------------------------------------------------- generic probe

GENERIC_ROUTES = [
    ("/dokumen?tipe_dokumen=1", "common_dokumen"),
    ("/dokumen/peraturan", "common_dokumen"),
    ("/dokumen/perda", "common_dokumen"),
    ("/peraturan?searchJenisPerda=1", "tulungagung"),
    ("/peraturan/jenis/perda/", "kapuashulu"),
    ("/inventarisasi-hukum/kategori/peraturan-daerah", "inventarisasi"),
    ("/home/kategori/peraturan-daerah", "lomboktengah"),
    ("/produkHukum?tipe_dokumen=1", "banjarmasin"),
    ("/dokumen/peraturan", "dokumen_view"),
    ("/pencarian?jenis=1", "kulonprogo"),
]


def generic_probe(sess, base, unit):
    """Try every known enumeration route; return (adapter_name, candidates)
    for the first that yields Perda candidates, else (None, census)."""
    census = {}
    # quick signature checks on canonical listing routes
    for path, adapter in GENERIC_ROUTES:
        try:
            probe_unit = dict(unit)
            if adapter == "common_dokumen":
                LIST_URLS["common_dokumen"][unit["bps"]] = path
            cands = ENUMERATORS[adapter](sess, base, probe_unit)
            census[path] = len(cands)
            if cands:
                return adapter, cands, census
        except Exception as e:
            census[path] = f"err {type(e).__name__}"
    return None, {}, census


# ---------------------------------------------------------------- harvest core

def cap_candidates(cands, hard_cap=CAP_HARD):
    """Sort recent-first; apply the tranche cap policy. Returns
    (selected, total, truncated_note)."""
    items = list(cands.values())

    def sort_key(c):
        try:
            y = int(c.get("tahun") or 0)
        except ValueError:
            y = 0
        try:
            n = int(re.sub(r"\D", "", str(c.get("nomor") or "0")) or 0)
        except ValueError:
            n = 0
        return (y, n)

    items.sort(key=sort_key, reverse=True)
    total = len(items)
    note = ""
    if total > CAP_FULL:
        recent = [c for c in items if not (c.get("tahun") or "").isdigit()
                  or int(c["tahun"]) >= CAP_RECENT_YEAR]
        if recent and len(recent) < len(items):
            note = (f"catalog {total} > {CAP_FULL}; restricted to "
                    f"{CAP_RECENT_YEAR}+/unknown-year ({len(recent)})")
            items = recent
    if len(items) > hard_cap:
        note += f"; hard-capped at {hard_cap}"
        items = items[:hard_cap]
    # dedupe by pdf/detail identity and (tahun, nomor)
    seen, out = set(), []
    for c in items:
        k = (c.get("pdf_url") or c.get("detail_url") or c["key"],
             c.get("tahun", ""), c.get("nomor", ""))
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out, total, note.strip("; ")


def harvest_unit(unit, state):
    bps = BPS_SCHEME.normalize(unit["bps"])
    host, base = unit["host"], f'https://{unit["host"]}'
    adapter = unit["adapter"]
    is_generic = adapter == "generic_probe"
    man = dict(unit, bps=bps, adapter=adapter, status="harvesting",
               catalog_total=0, selected=0, acts=0, rows=0, failed_docs=[],
               requests=0, errors=[], truncation="")
    sess = PoliteSession()
    t0 = time.monotonic()
    try:
        prefixes = ["/dokumen", "/peraturan", "/prokum", "/home", "/produkHukum",
                    "/pencarian", "/inventarisasi-hukum", "/produk", "/category",
                    "/common", "/storage", "/dokumen.php", "/cari"]
        if robots_blocked(sess, base, prefixes):
            man["status"] = "skipped"
            man["errors"].append("robots.txt disallows a needed path (live check)")
            return man
        if adapter == "generic_probe":
            found_adapter, cands, census = generic_probe(sess, base, unit)
            man["generic_census"] = census
            if not found_adapter:
                man["status"] = "skipped"
                man["errors"].append("generic sample: no known adapter route "
                                     "yielded Perda candidates")
                return man
            adapter = found_adapter
            man["adapter"] = f"generic->{adapter}"
            unit = dict(unit, adapter=adapter)
        else:
            cands = ENUMERATORS[adapter](sess, base, unit)
        if not cands:
            man["status"] = "skipped"
            man["errors"].append("enumeration yielded 0 Perda candidates "
                                 "(template mismatch or empty catalog)")
            return man
        hard = GENERIC_CAP if is_generic else CAP_HARD
        selected, total, note = cap_candidates(cands, hard_cap=hard)
        man["catalog_total"] = total
        man["selected"] = len(selected)
        man["truncation"] = note
        budget = float(os.environ.get("ID_UNIT_BUDGET_S", "1500"))
        rows = []
        for cand in selected:
            if time.monotonic() - t0 > budget:
                man["truncation"] = (man["truncation"] + "; " if man["truncation"]
                                     else "") + (
                    f"partial: unit time budget {int(budget)}s hit — "
                    f"{man['acts']} of {len(selected)} selected docs harvested "
                    f"(host stalls); remainder pending a top-up pass")
                break
            info = dict(title=cand.get("title", ""), nomor=cand.get("nomor", ""),
                        tahun=cand.get("tahun", ""), rows=0,
                        detail_url=cand.get("detail_url", ""),
                        pdf_url=cand.get("pdf_url", ""), mode="")
            try:
                doc = cand
                needs_detail = (adapter in RESOLVER_ADAPTERS
                                or not doc.get("pdf_url") or not doc.get("title"))
                if needs_detail and doc.get("detail_url"):
                    doc = resolve_pdf(sess, dict(cand))
                    if cand.get("title_locked") and cand.get("title"):
                        # The enumerator's catalog title is authoritative
                        # (DIH detail pages yield metadata-junk titles like
                        # 'Peraturan Daerah Status Berlaku Bahasa ...').
                        doc["title"] = cand["title"]
                    info.update({k: doc.get(k, info.get(k, "")) for k in
                                 ("title", "nomor", "tahun", "pdf_url")})
                if not doc.get("pdf_url"):
                    info["mode"] = "no PDF link on detail page"
                    man["failed_docs"].append(info)
                    continue
                text, nbytes, err = pdf_text(sess, doc["pdf_url"])
                info["pdf_bytes"] = nbytes
                if err or not text:
                    info["mode"] = f"pdf failed: {err or 'empty text (scanned?)'}"
                    man["failed_docs"].append(info)
                    continue
                head_type = pdf_head_reg_type(text)
                qanun_ok = bool(unit.get("qanun_equivalent"))
                if head_type and head_type != "DAERAH" and not (
                        qanun_ok and is_qanun_title(doc.get("title", ""))):
                    info["mode"] = (f"wrong type: PDF head is Peraturan "
                                    f"{head_type.title()}, not Perda")
                    man["failed_docs"].append(info)
                    continue
                chunks = split_pasal(text)
                if not chunks:
                    info["mode"] = "no Pasal structure parsed"
                    man["failed_docs"].append(info)
                    continue
                title = doc.get("title") or info["title"]
                head_title = pdf_head_title(text)
                if head_title and (not is_perda_title(title) or len(title) < 60
                                   or "•" in title
                                   or title.lower().count("peraturan daerah") > 1):
                    title, info["title"] = head_title, head_title
                # Qanun policy (Benjamin 2026-10-13): on flagged Aceh
                # dih units, a Qanun-headed catalog title is the
                # instrument's real name — keep it verbatim, do not
                # synthesize a Peraturan Daerah title around it.
                qanun_doc = bool(unit.get("qanun_equivalent")) \
                    and is_qanun_title(title or "")
                if qanun_doc:
                    pass
                elif title and not is_perda_title(title) and doc.get("nomor"):
                    title = (f"Peraturan Daerah Nomor {doc['nomor']} Tahun "
                             f"{doc.get('tahun', '')} — {title}")
                elif not is_perda_title(title):
                    title = (f"Peraturan Daerah Nomor {doc.get('nomor', '')} "
                             f"Tahun {doc.get('tahun', '')}").strip()
                if head_reg_type(title) not in ("daerah", "") and not qanun_doc:
                    info["mode"] = (f"wrong type: title heads with Peraturan "
                                    f"{head_reg_type(title)}, not Perda")
                    man["failed_docs"].append(info)
                    continue
                info["title"] = title
                kind = "qanun" if qanun_doc else "perda"
                base_id = (f"id-{bps}-{kind}-{doc.get('tahun', '')}-"
                           f"{slug(str(doc.get('nomor', '')))}")
                regeling = f"jdih:{host}:{doc.get('key', '')}"
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
                info["mode"] = "pdf-pasal"
                if info["rows"] > 0:
                    man["acts"] += 1
            except Exception as exc:
                info["mode"] = f"failed: {exc!r}"
                man["failed_docs"].append(info)
        rows = finalize_rows(rows)
        table = rows_to_table(rows)
        errors = validate_table(table, jurisdiction_id=bps,
                                jurisdiction_name=unit["name"], country="ID")
        man["validation_errors"] = errors
        report = validation_report(table, jurisdiction_id=bps,
                                   jurisdiction_name=unit["name"], country="ID")
        write_validation_report(STAGE / f"{bps}_validation.json", report)
        if errors:
            man["status"] = "failed"
            man["errors"].append(f"validation FAILED: {errors}")
        elif table.num_rows:
            man["rows"] = write_html_parquet(STAGE / f"{bps}_html.parquet", table)
            man["status"] = "staged"
        else:
            man["status"] = "skipped"
            man["errors"].append("0 rows harvested (all docs failed extraction)")
    except Exception as exc:
        man["status"] = "failed"
        man["errors"].append(f"harvest failed: {exc!r}")
    finally:
        man["requests"] = sess.n_requests
        man["wall_seconds"] = round(time.monotonic() - t0, 1)
    return man


def run(units, mode):
    state = load_state()
    for bps, (name, host, why) in PRESKIP.items():
        if bps not in state:
            state[bps] = dict(bps=bps, name=name, host=host, status="skipped",
                              errors=[why], acts=0, rows=0)
    save_state(state)
    todo = []
    for bps, name, host, adapter in units:
        cur = state.get(bps, {})
        if cur.get("status") in ("staged", "published"):
            print(f"[{bps}] already {cur['status']}, skip", flush=True)
            continue
        todo.append(dict(bps=bps, name=name, host=host, adapter=adapter))
    if mode == "enum":
        def enum_one(unit):
            sess = PoliteSession()
            base = f'https://{unit["host"]}'
            try:
                if unit["adapter"] == "generic_probe":
                    fa, cands, census = generic_probe(sess, base, unit)
                    return unit["bps"], dict(adapter=fa, n=len(cands),
                                             census=census,
                                             sample=[(c.get("tahun"), c.get("nomor"),
                                                      (c.get("title") or "")[:70])
                                                     for c in list(cands.values())[:3]])
                cands = ENUMERATORS[unit["adapter"]](sess, base, unit)
                return unit["bps"], dict(adapter=unit["adapter"], n=len(cands),
                                         sample=[(c.get("tahun"), c.get("nomor"),
                                                  (c.get("title") or "")[:70])
                                                 for c in list(cands.values())[:3]])
            except Exception as e:
                return unit["bps"], dict(error=repr(e))
        with ThreadPoolExecutor(max_workers=6) as ex:
            for bps, res in ex.map(enum_one, todo):
                print(bps, json.dumps(res, ensure_ascii=False), flush=True)
        return
    workers = int(os.environ.get("ID_WORKERS", "5"))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for man in ex.map(lambda u: harvest_unit(u, state), todo):
            state[man["bps"]] = {k: v for k, v in man.items()}
            save_state(state)
            print(json.dumps({k: man[k] for k in
                              ("bps", "name", "adapter", "status", "catalog_total",
                               "selected", "acts", "rows", "requests", "errors")
                              if k in man}, ensure_ascii=False), flush=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "harvest"
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
    units = [(b, n, h, a) for b, n, h, a in UNITS if not only or b in only]
    if not only or "generic" in only:
        units += [(b, n, h, "generic_probe") for b, n, h in GENERIC_UNITS
                  if not only or b in only or "generic" in only]
    if mode == "harvest":
        order = os.environ.get("ID_ORDER", "")
        if order:
            rank = {b: i for i, b in enumerate(order.split(","))}
            units.sort(key=lambda u: rank.get(u[0], 99))
    run(units, mode)


if __name__ == "__main__":
    main()
