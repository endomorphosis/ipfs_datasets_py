#!/usr/bin/env python3
"""Mexico: municipal reglamentos / bandos published in the STATE official gazettes (periódicos oficiales).

One adapter per state: day(f, d) -> [item] (doc_id, title, municipio, pdf/url ...), text(f, it) -> text.
Walks newest day first (today -> floor), resumable cursor per state in _state/mx_gazettes/<state>.json.
Targets: titles that are a reglamento / bando / código municipal / ordenamiento issued by an ayuntamiento/municipio
(state-level reglamentos of laws are excluded). Place: municipio name + state INEGI prefix -> wd_P3801 ->
candidate-list place_id. Unmatched -> _unmatched/MX. Scanned PDFs (no text layer) -> _scanned_pdfs_manifest.jsonl.
Politeness: es_bop.Fetcher (identifying UA, >= min interval per host, robots per common/robots_policy.json:
respect_robots false -> records tagged robots_ignored_owner_policy_20261101). Never circumvents WAF/captcha.
"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
from html import unescape as html_unescape
import argparse, csv, hashlib, json, logging, os, re, sys, time, unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, str(HERE.parent / "es")); sys.path.insert(0, str(HERE.parent))
import schema as S  # noqa: E402
from es_bop import Fetcher, Blocked, CaptchaChallenge, pdf_text, RP  # noqa: E402
from common import scanned_pdfs as SP  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
OUT, QUAR, UNM, STATE = STAGE / "MX", STAGE / "_quarantine" / "MX", STAGE / "_unmatched" / "MX", STAGE / "_state" / "mx_gazettes"
log = logging.getLogger("mx_gazettes")
TARGET = re.compile(r"\b(reglamento|bando|c[oó]digo\s+(municipal|reglamentario)|ordenamiento|ordenanza|lineamientos?\s+municipal)", re.I)
MUNI = re.compile(r"(ayuntamiento|municipio|municipal)", re.I)
EXCL = re.compile(r"\bedictos?\b|convocatoria|licitaci|presupuesto de egresos|ley de ingresos|tabla de valores|fe de erratas", re.I)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(municipio|municipality)\s+de\s+|\s+municipality$", "", s.strip())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def load_places(prefix):
    cand = {r["qid"]: r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv")))
            if r["country_code"] == "MX"}
    by = {}
    for r in csv.DictReader(open(HERE / "wd_P3801_sites.csv")):
        if not r["code"].startswith(prefix) or len(r["code"]) != 5:
            continue
        q = r["item"].rsplit("/", 1)[1]
        c = cand.get(q, {})
        p = {"place_id": c.get("place_id") or f"wd:{q}", "qid": q, "inegi": r["code"],
             "place_name": (r["label"] or c.get("place_name", "")).replace("Municipio de ", "").replace(" Municipality", "")}
        for n in {norm(r["label"]), norm(c.get("place_name", ""))} - {""}:
            by.setdefault(n, {})[q] = p
    return {n: next(iter(v.values())) for n, v in by.items() if len(v) == 1}


def find_muni(title, places):
    """'... del Municipio de Zapopan, Jalisco' / 'Ayuntamiento de Tlaquepaque' / 'municipal de Tonalá'."""
    for m in re.finditer(r"(?:municipio|ayuntamiento(?:\s+constitucional)?|municipal)\s+de\s+([A-ZÁÉÍÓÚÑ][\w\sáéíóúñÁÉÍÓÚÑ.'-]{2,60})", title, re.I):
        words = m.group(1).split()
        for k in range(min(len(words), 7), 0, -1):          # longest prefix that is a known municipio of the state
            cand = norm(" ".join(words[:k]).rstrip(".,;"))
            if cand in places:
                return places[cand], " ".join(words[:k]).rstrip(".,;")
    return None, None


class Jalisco:
    """Periódico Oficial "El Estado de Jalisco" (periodicooficial.jalisco.gob.mx, Angular SPA). Public JSON API used by
    the site itself: apiperiodico.jalisco.gob.mx/api/newspaper/public?fecha=YYYY-MM-DD&page=1&perPage=50 (editions of
    the day with their sumario 'description'); /newspaper/public/find?id=N -> 'link' (getAsset PDF). One record per
    edition (sección) whose sumario names a municipal reglamento/bando; publishes daily incl. weekends (special editions)."""
    key, iso, prefix = "jalisco", "MX-JAL", "14"
    A = "https://apiperiodico.jalisco.gob.mx/api/newspaper/"
    home = "https://periodicooficial.jalisco.gob.mx/"
    min_interval = 1.5
    floor = "2000-01-01"

    def day(self, f, d):
        r = f.get(f"{self.A}public?fecha={d:%Y-%m-%d}&search=&page=1&perPage=100")
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        if r.text.lstrip()[:1] != "{":
            raise CaptchaChallenge("non-JSON answer")
        data = r.json()["result"]["data"]
        out = []
        for e in data:
            desc = " ".join((e.get("description") or "").split())
            # sumario lines are ' - <page> ' separated; keep the segments that are municipal regulations
            segs = [s.strip() for s in re.split(r"\s-\s(?:Pag\.\s*)?\d+\s*", desc) if s.strip()]
            hits = [s for s in segs if TARGET.search(s) and MUNI.search(s) and not EXCL.search(s)]
            if hits:
                out.append({"doc_id": f"POEJ-{e['id_newspaper']}", "eid": e["id_newspaper"], "titles": hits, "sumario": desc,
                            "number": e.get("number"), "tomo": e.get("tomo"), "special": e.get("special_description")})
        return len(data) > 0, out

    def text(self, f, it):
        r = f.get(f"{self.A}public/find?id={it['eid']}")
        j = r.json()["result"]
        link = j.get("link")
        if not link:
            raise IOError("no pdf link")
        r2 = f.get(link)
        if r2.status_code != 200 or r2.content[:4] != b"%PDF":
            raise IOError(f"pdf HTTP {r2.status_code}")
        return pdf_text(r2.content), link, j.get("municipality_id")


class Guanajuato:
    """Periódico Oficial del Gobierno del Estado de Guanajuato (periodico.guanajuato.gob.mx, Angular SPA). Public JSON
    used by the site: backperiodico.guanajuato.gob.mx/api/Periodico/BusquedaPeriodicoPublicacion/null/null/null/null/null/
    <page>/<size> (all editions/parts newest first: perid, perfecha DD/MM/YYYY, pernumero, perparte) and
    Periodico/DescargarPeriodicoId/<perid> (PDF). The PDF sumario (pp. 2..) lists issuer headings ('MUNICIPIO DE X, GTO.')
    and entries ending in their page number; printed page N == PDF page N. One record per municipal sumario entry,
    cut by page range [N, next N]."""
    key, iso, prefix = "guanajuato", "MX-GUA", "11"
    A = "https://backperiodico.guanajuato.gob.mx/api/Periodico/"
    home = "https://periodico.guanajuato.gob.mx/"
    min_interval = 1.5
    floor = "2000-01-01"

    def __init__(self):
        self.by_date, self.page, self.oldest, self.end = {}, 0, None, False
        self._pdf = (None, None)

    def _list_until(self, f, d):
        while not self.end and (self.oldest is None or self.oldest >= d):
            self.page += 1
            r = f.get(f"{self.A}BusquedaPeriodicoPublicacion/null/null/null/null/null/{self.page}/50")
            if r.status_code != 200 or r.text.lstrip()[:1] != "{":
                raise IOError(f"list HTTP {r.status_code}")
            objs = r.json().get("objeto") or []
            if not objs:
                self.end = True; break
            for o in objs:
                dd = datetime.strptime(o["perfecha"], "%d/%m/%Y").date()
                self.by_date.setdefault(dd, {})[o["perid"]] = o
                self.oldest = dd if self.oldest is None else min(self.oldest, dd)

    def _get_pdf(self, f, perid):
        if self._pdf[0] != perid:
            u = f"{self.A}DescargarPeriodicoId/{perid}"
            r = f.get(u)
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"pdf HTTP {r.status_code}")
            self._pdf = (perid, r.content)
        return self._pdf[1]

    def day(self, f, d):
        self._list_until(f, d)
        eds = self.by_date.pop(d, {})
        out = []
        for perid, o in sorted(eds.items()):
            b = self._get_pdf(f, perid)
            pages = pdf_text(b).split("\f")
            if len("".join(pages).strip()) < 200:
                SP.append([SP.record(f"POEGTO-{perid}", "mx_gaz_guanajuato_edition", "MX", f"{self.A}DescargarPeriodicoId/{perid}",
                                     RP.policy(self.A, "robots_allowed_rfc9309"))]); continue
            sm = "\n".join(pages[1:8])
            k = sm.find("SUMARIO")
            if k < 0:
                continue
            entries, iss, buf = [], "", []
            for ln in sm[k:].split("\n"):
                st_ = ln.strip()
                if not st_ or re.match(r"^(P[ÁA]GINA \d+|PERI[ÓO]DICO OFICIAL)\b", st_) or "pulsar o hacer clic" in st_ or st_.startswith("SUMARIO") or st_.startswith("el Sumario"):
                    continue
                m = re.match(r"^(.*?)\s{2,}(\d{1,4})$", st_) or re.match(r"^(.*?[.)”\"])\s*(\d{1,4})$", st_)
                if m:
                    buf.append(m.group(1)); entries.append((iss, " ".join(" ".join(buf).split()), int(m.group(2)))); buf = []
                elif st_ == st_.upper() and re.search(r"[A-ZÁÉÍÓÚÑ]{4}", st_) and len(st_) < 110 and not buf:
                    iss = st_
                else:
                    buf.append(st_)
                if entries and len(entries) > 3 and entries[-1][2] < entries[-2][2]:
                    entries.pop(); break                       # ran past the sumario into the body
            for i, (iss_, t, pg) in enumerate(entries):
                if not (iss_.upper().startswith("MUNICIPIO") and TARGET.search(t) and not EXCL.search(t)):
                    continue
                nxt = next((p for (_, _, p) in entries[i + 1:] if p > pg), len(pages))
                out.append({"doc_id": f"POEGTO-{perid}-p{pg}", "perid": perid, "titles": [t], "issuer": iss_, "sumario": t,
                            "number": str(o.get("pernumero")), "special": o.get("perdescripcion"), "page": pg, "page_to": nxt})
        return bool(eds), out

    def text(self, f, it):
        b = self._get_pdf(f, it["perid"])
        pages = pdf_text(b).split("\f")
        t = "\n".join(pages[it["page"] - 1: max(it["page"], it["page_to"] - 1)])
        return t, f"{self.A}DescargarPeriodicoId/{it['perid']}#page={it['page']}", None


def _nrm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def slice_by_titles(text, titles, skip=0):
    """Cut a whole-edition text into per-entry segments: locate each sumario title (first ~45 normalized chars) in the
    body after `skip` chars, in order; segment = [pos_i, pos_{i+1}). Returns {index: segment} for located titles."""
    n, idx = [], []
    for ch_i, ch in enumerate(text):
        c = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode().lower()
        if c.isalnum():
            n.append(c); idx.append(ch_i)
    ns = "".join(n)
    start = next((k for k, v in enumerate(idx) if v >= skip), 0)
    occ = {}
    for i, t in enumerate(titles):
        key = _nrm(t)[:45]
        if len(key) < 20:
            continue
        j, L = ns.find(key, start), []
        while j >= 0:
            L.append(j); j = ns.find(key, j + 1)
        if L:
            occ[i] = L
    out = {}
    for i, L in occ.items():
        p = L[0]
        nxt = [q for k, M in occ.items() if k != i for q in M if q > p]
        end = idx[min(nxt)] if nxt else len(text)
        out[i] = text[idx[p]:end]
    return out


class Hidalgo:
    """Periódico Oficial del Estado de Hidalgo (periodico.hidalgo.gob.mx, WordPress + The Events Calendar). One 'event'
    per edition: REST ?rest_route=/tribe/events/v1/events&start_date=D&end_date=D -> description with the Sumario
    ('Municipio de X, Hidalgo.- <title>'); the event HTML page links the PDF (/POEHpdfpublic/<file>.pdf). Each municipal
    target entry is cut out of the edition text by locating its title (and the next entry's) in the body."""
    key, iso, prefix = "hidalgo", "MX-HID", "13"
    B = "https://periodico.hidalgo.gob.mx/"
    home = B
    min_interval = 1.5
    floor = "2000-01-01"

    def __init__(self):
        self._pdf = (None, None)

    def day(self, f, d):
        r = f.get(f"{self.B}?rest_route=/tribe/events/v1/events&start_date={d:%Y-%m-%d}&end_date={d:%Y-%m-%d} 23:59:59&per_page=50")
        if r.status_code == 404:
            return False, []
        if r.status_code != 200 or r.text.lstrip()[:1] != "{":
            raise IOError(f"HTTP {r.status_code}")
        evs = [e for e in r.json().get("events", []) if e["start_date"][:10] == d.isoformat()]
        out = []
        for e in evs:
            entries = [" ".join(html_unescape(re.sub(r"<[^>]+>", " ", x)).split())
                       for x in re.split(r"</p>|<br\s*/?>|</li>|</td>|\t", e["description"])]
            entries = [x for x in entries if len(x) > 15]
            ents = []
            for x in entries:
                m = re.match(r"^(Municipio de [^.]+?),?\s*(?:Hidalgo|Hgo)?\.?\s*[.-]+\s*(.+)$", x)
                ents.append((m.group(1), m.group(2), x) if m else (None, x, x))
            for i, (iss, t, raw) in enumerate(ents):
                if iss and TARGET.search(t) and not EXCL.search(t):
                    out.append({"doc_id": f"POEH-{e['id']}-{i}", "eid": e["id"], "url": e["url"], "titles": [t], "issuer": iss,
                                "sumario": raw, "all_titles": [x[1] for x in ents], "idx": i, "special": e["title"]})
        return bool(evs), out

    def text(self, f, it):
        if self._pdf[0] != it["eid"]:
            r = f.get(it["url"])
            m = re.search(r"(https://periodico\.hidalgo\.gob\.mx/POEHpdfpublic/[^\"'&#\s]+\.pdf)", r.text)
            if not m:
                raise IOError("no POEHpdfpublic link")
            r2 = f.get(m.group(1))
            if r2.status_code != 200 or r2.content[:4] != b"%PDF":
                raise IOError(f"pdf HTTP {r2.status_code}")
            self._pdf = (it["eid"], (m.group(1), pdf_text(r2.content)))
        u, full = self._pdf[1]
        pages = full.split("\f")
        skip = len("\f".join(pages[:2]))
        seg = slice_by_titles(full, it["all_titles"], skip=skip).get(it["idx"])
        if not seg:   # Morelos-style: shorter keys, else skip (no whole-edition fallback)
            seg = slice_by_titles(full, [t[:30] if len(_nrm(t[:30])) >= 20 else t for t in it["all_titles"]], skip=skip).get(it["idx"])
        if not seg:
            raise Unlocated("title not located in edition text")
        it["split"] = "title_located"
        return seg, u, None


class SLP:
    """Periódico Oficial del Estado de San Luis Potosí (periodicooficial.slp.gob.mx, Laravel + Vue). Public JSON used by
    the site's 'Consulta' page: /api/publicacion/<YYYY-MM-DD>/gt -> nivel1 (Municipal) / nivel2 / nivel3, one entry per
    published document (id, titulo, segundo = municipio, autoridad_emisora, pdf); PDF via
    /api/publicacion/descargar/guest/<id>/documento. One record per municipal document (already split by the source)."""
    key, iso, prefix = "slp", "MX-SLP", "24"
    B = "https://periodicooficial.slp.gob.mx/api/publicacion/"
    home = "https://periodicooficial.slp.gob.mx/"
    min_interval = 1.5
    floor = "2000-01-01"

    def day(self, f, d):
        r = f.get(f"{self.B}{d:%Y-%m-%d}/gt?order=recent")
        if r.status_code != 200 or r.text.lstrip()[:1] != "{":
            raise IOError(f"HTTP {r.status_code}")
        j = r.json()
        allp = [x for k in ("nivel1", "nivel2", "nivel3") for x in (j.get(k) or [])]
        out = []
        for x in j.get("nivel1") or []:
            t = " ".join((x.get("titulo") or "").split())
            if TARGET.search(t) and not EXCL.search(t):
                out.append({"doc_id": f"POESLP-{x['id']}", "pid": x["id"], "titles": [t], "issuer": f"Municipio de {(x.get('segundo') or '').title()}",
                            "sumario": f"{x.get('segundo')} / {x.get('autoridad_emisora')}: {t}", "special": x.get("pdf"), "split": "source_document"})
        return bool(allp), out

    def text(self, f, it):
        u = f"{self.B}descargar/guest/{it['pid']}/documento"
        r = f.get(u)
        if r.status_code != 200 or r.content[:4] != b"%PDF":
            raise IOError(f"pdf HTTP {r.status_code}")
        return pdf_text(r.content), u, None


MIN_DOC_CHARS = 1500
_TOC_LINE = re.compile(r"(\.{4,}|…{2,}|\bP[áa]g(ina)?\.?\s*\d+\s*$|^\s*\d{1,4}\s*$)", re.I)


def index_like(text, titles=()):
    """True for very short docs or TOC/sumario-only segments: many dotted-leader / 'Pág. N' / bare page-number lines,
    or most of the text made of other sumario titles."""
    t = text.strip()
    if len(t) < MIN_DOC_CHARS:
        return "short"
    lines = [l for l in t.split("\n") if l.strip()]
    if lines and sum(1 for l in lines if _TOC_LINE.search(l)) / len(lines) > 0.25:
        return "toc_lines"
    if len(titles) > 2:
        nt = _nrm(t)
        hit = sum(len(_nrm(x)[:60]) for x in titles if len(_nrm(x)) >= 20 and _nrm(x)[:45] in nt)
        if hit > 0.5 * max(1, len(nt)):
            return "toc_titles"
    return None


class Aguascalientes:
    """Periódico Oficial del Estado de Aguascalientes (eservicios2.aguascalientes.gob.mx/periodicooficial, ASP.NET).
    The site's own page methods (JSON POST, same calls its JS makes): Default.aspx/obtenerInformacion (editions in a
    date range) and Default.aspx/obtenerDetalle (documents of an edition: NombreDocumento, Pagina, Dependencia,
    TipoPublicacion). PDF: /PeriodicoOficial/Archivos/<IdPeriodico>.pdf. Records = municipal (H. AYUNTAMIENTO DE X)
    target documents cut by page range [Pagina, next Pagina)."""
    key, iso, prefix = "aguascalientes", "MX-AGU", "01"
    B = "https://eservicios2.aguascalientes.gob.mx/periodicooficial/Default.aspx/"
    home = "https://eservicios2.aguascalientes.gob.mx/periodicooficial/"
    min_interval = 1.5
    floor = "2000-01-01"
    F = {"actualIndice": None, "IdOrdenGobierno": "0", "IdDependencia": "0", "numero": "", "IdEdicion": "0", "IdTipoPublicacion": "0",
         "NombreDocumento": "", "IdTomo": "", "IdSeccion": "0", "Contenido": ""}

    def __init__(self):
        self._pdf = (None, None)

    def _post(self, f, meth, body):
        r = f.s.post(self.B + meth, json=body, timeout=60, headers={"Content-Type": "application/json; charset=utf-8"})
        f.nreq += 1
        time.sleep(self.min_interval)
        if r.status_code != 200 or r.text.lstrip()[:1] != "{":
            raise IOError(f"{meth} HTTP {r.status_code}")
        d = r.json().get("d") or ""
        return json.loads(d) if d else []

    def day(self, f, d):
        f.allowed(self.home)                                   # robots policy bookkeeping / tagging
        rng = {"fipub": f"{d.month}/{d.day}/{d.year} 0:0:0", "ffpub": f"{d.month}/{d.day}/{d.year} 23:59:59"}
        eds = [e for e in self._post(f, "obtenerInformacion", {**rng, **self.F, "indiceActual": 0})
               if (e.get("FechaPublicacion") or "")[:10] == d.isoformat()]
        out = []
        for e in eds:
            docs = self._post(f, "obtenerDetalle", {"id": e["IdPeriodico"], **rng, **self.F})
            docs.sort(key=lambda x: int(x.get("Pagina") or 0))
            for i, x in enumerate(docs):
                t, dep = " ".join((x.get("NombreDocumento") or "").split()), (x.get("Dependencia") or "")
                if "AYUNTAMIENTO" in dep.upper() and (TARGET.search(t) or (x.get("TipoPublicacion") or "").upper().startswith("REGLAMENTO")) and not EXCL.search(t):
                    pg = int(x.get("Pagina") or 1)
                    nxt = next((int(y["Pagina"]) for y in docs[i + 1:] if int(y.get("Pagina") or 0) > pg), None)
                    out.append({"doc_id": f"POEAGS-{e['IdPeriodico']}-p{pg}", "pid": e["IdPeriodico"], "titles": [t],
                                "issuer": re.sub(r"^H\.\s*AYUNTAMIENTO\s+(DEL MUNICIPIO\s+)?DE\s+", "Municipio de ", dep.strip(), flags=re.I),
                                "sumario": f"{dep}: {t}", "number": str(e.get("Numero")), "tomo": e.get("Tomo"), "special": e.get("Edicion"),
                                "page": pg, "page_to": nxt or 10 ** 6, "open_end": nxt is None,
                                "all_titles": [" ".join((y.get("NombreDocumento") or "").split()) for y in docs], "idx": i})
        return bool(eds), out

    def text(self, f, it):
        u = f"https://eservicios2.aguascalientes.gob.mx/PeriodicoOficial/Archivos/{it['pid']}.pdf"
        if self._pdf[0] != it["pid"]:
            r = f.get(u)
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"pdf HTTP {r.status_code}")
            self._pdf = (it["pid"], pdf_text(r.content).split("\f"))
        pages = self._pdf[1]
        it["page_to"] = min(it["page_to"], len(pages) + 1)
        if it.get("open_end"):                        # last entry of the edition: cap the range (was: to end of PDF)
            it["page_to"] = min(it["page_to"], it["page"] + 60)
        # Pagina is the entry's start page; the range can hold the previous/next entry's tail -> cut by title location
        rng = "\f".join(pages[max(0, it["page"] - 2): max(it["page"], it["page_to"] - 1)])
        seg = slice_by_titles(rng, it.get("all_titles") or it["titles"]).get(it.get("idx", 0)) if it.get("all_titles") else None
        if seg and len(seg.strip()) >= MIN_DOC_CHARS:
            it["split"] = "page_range+title_located"
            return seg, f"{u}#page={it['page']}", None
        it["split"] = "page_range"
        return "\n".join(pages[it["page"] - 1: max(it["page"], it["page_to"] - 1)]), f"{u}#page={it['page']}", None


class Unlocated(Exception):
    pass


class Morelos:
    """Periódico Oficial "Tierra y Libertad" (periodico.morelos.gob.mx, Laravel). Public DataTables endpoint used by
    /ejemplares: POST ejemplaresFiltradosPublicoGeneral (anios, mes; CSRF token from the page) -> every publication
    (main issue + parts like 6619_7A) of the month with its HTML sumario (<strong><u>HEADING</u></strong>, entries,
    'Pág. N'); PDF /obtenerPDF/<URL>. Municipal target entries (heading AYUNTAMIENTO ... DE X) are cut out of the
    publication text by title location. Parts are processed before the main issue; duplicates (same title) skipped."""
    key, iso, prefix = "morelos", "MX-MOR", "17"
    B = "https://periodico.morelos.gob.mx/"
    home = B + "ejemplares"
    min_interval = 1.5
    floor = "2000-01-01"

    def __init__(self):
        self.months, self.tok, self._pdf, self.seen = {}, None, (None, None), set()

    def _month(self, f, y, m):
        if (y, m) in self.months:
            return self.months[(y, m)]
        if not self.tok:
            r = f.get(self.home)
            mt = re.search(r'csrf-token" content="([^"]+)', r.text)
            if not mt:
                raise IOError("no csrf token")
            self.tok = mt.group(1)
        rows, start = [], 0
        while True:
            w = f.next.get("periodico.morelos.gob.mx", 0) - time.time()
            if w > 0:
                time.sleep(w)
            f.next["periodico.morelos.gob.mx"] = time.time() + self.min_interval
            r = f.s.post(self.B + "ejemplaresFiltradosPublicoGeneral", timeout=60,
                         headers={"X-CSRF-TOKEN": self.tok, "X-Requested-With": "XMLHttpRequest"},
                         data={"draw": "1", "start": str(start), "length": "100", "anios": str(y), "mes": str(m), "buscarSumario": "",
                               "search[value]": "", "order[0][column]": "3", "order[0][dir]": "desc", "columns[3][data]": "fechaPublicacion"})
            f.nreq += 1
            if r.status_code in (419, 401, 403):
                self.tok = None
                raise IOError(f"list HTTP {r.status_code}")
            j = r.json()
            if "data" not in j:
                self.tok = None; raise IOError(f"list error {str(j)[:100]}")
            rows += j["data"]; start += 100
            if start >= int(j.get("recordsFiltered") or 0):
                break
        by = {}
        for x in rows:
            by.setdefault(x["fechaPublicacion"][:10], []).append(x)
        self.months = {(y, m): by}                              # keep one month in memory
        return by

    def day(self, f, d):
        f.allowed(self.home)
        pubs = self._month(f, d.year, d.month).get(d.isoformat(), [])
        pubs.sort(key=lambda x: ("_" not in x["nomPublicacion"], x["nomPublicacion"]))
        out = []
        for x in pubs:
            sm = x.get("sumario") or ""
            ents, head = [], ""
            for blk in re.findall(r"<p[^>]*>(.*?)</p>", sm, re.S):
                hm = re.match(r"\s*<strong><u>(.*?)</u></strong>\s*$", blk, re.S)
                t = " ".join(html_unescape(re.sub(r"<[^>]+>", " ", blk)).split())
                if hm:
                    head = t; continue
                if not t or re.match(r"^[….\s]*P[áa]g\.?\s*\d+", t):
                    continue
                ents.append((head, t))
            titles = [t for _, t in ents]
            for i, (h, t) in enumerate(ents):
                if re.search(r"AYUNTAMIENTO|MUNICIPIO DE", h, re.I) and TARGET.search(t) and not EXCL.search(t):
                    k = _nrm(t)[:80]
                    if (d, k) in self.seen:
                        continue
                    self.seen.add((d, k))
                    out.append({"doc_id": f"POEMOR-{x['nomPublicacion']}-{i}", "url": self.B + "obtenerPDF" + x["URL"], "titles": [t],
                                "issuer": re.sub(r"^AYUNTAMIENTO( CONSTITUCIONAL)? DE\s+", "Municipio de ", h.strip(), flags=re.I),
                                "sumario": f"{h}: {t}", "number": x["nomPublicacion"], "special": x.get("edicion"), "all_titles": titles, "idx": i})
        return bool(pubs), out

    def text(self, f, it):
        if self._pdf[0] != it["url"]:
            r = f.get(it["url"])
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"pdf HTTP {r.status_code}")
            self._pdf = (it["url"], pdf_text(r.content))
        full = self._pdf[1]
        pages = full.split("\f")
        skip = len("\f".join(pages[:1]))
        seg = slice_by_titles(full, it["all_titles"], skip=skip).get(it["idx"])
        if not seg:   # shorter keys (titles reflowed/hyphenated in the PDF)
            seg = slice_by_titles(full, [t[:30] if len(_nrm(t[:30])) >= 20 else t for t in it["all_titles"]], skip=skip).get(it["idx"])
        if not seg:
            raise Unlocated("title not located in publication text")
        it["split"] = "title_located"
        return seg, it["url"], None


class Nayarit:
    """Periódico Oficial del Estado de Nayarit (periodicooficial.nayarit.gob.mx). The /publicaciones page's own AJAX:
    POST controllers/PublicacionesController.php (tipo=fecha, datos='fecha=YYYY-MM-DD', pagina=N; 10 per page) -> one
    row per sección (separate PDF): sumario, tipo, nombre_pdf; PDF descargar_pdf.php?archivo=<nombre_pdf>.pdf.
    Records = secciones whose sumario is a municipal reglamento/bando (MUNICIPIO/AYUNTAMIENTO DE X)."""
    key, iso, prefix = "nayarit", "MX-NAY", "18"
    B = "https://periodicooficial.nayarit.gob.mx/"
    home = B + "publicaciones"
    min_interval = 1.5
    floor = "2000-01-01"

    def _post(self, f, data):
        w = f.next.get("periodicooficial.nayarit.gob.mx", 0) - time.time()
        if w > 0:
            time.sleep(w)
        f.next["periodicooficial.nayarit.gob.mx"] = time.time() + self.min_interval
        r = f.s.post(self.B + "controllers/PublicacionesController.php", data=data, timeout=60)
        f.nreq += 1
        if r.status_code != 200 or r.text.lstrip()[:1] != "{":
            raise IOError(f"HTTP {r.status_code}")
        return r.json()

    def day(self, f, d):
        f.allowed(self.home)
        rows, pg = [], 1
        while True:
            j = self._post(f, {"tipo": "fecha", "datos": f"fecha={d:%Y-%m-%d}", "pagina": str(pg)})
            rows += j.get("resultados") or []
            if pg * int(j.get("resultadosPorPagina") or 10) >= int(j.get("total") or 0):
                break
            pg += 1
        out = []
        for x in rows:
            t = " ".join((x.get("sumario") or "").replace("-", " ").split()) if set((x.get("sumario") or "")[:20]) <= {"-"} else " ".join((x.get("sumario") or "").split())
            if (TARGET.search(t) or (x.get("tipo") or "").upper() == "REGLAMENTO") and re.search(r"MUNICIPIO|AYUNTAMIENTO", t, re.I) and not EXCL.search(t):
                out.append({"doc_id": f"POENAY-{x['id']}", "pdf": x["nombre_pdf"], "titles": [t[:1000]], "sumario": t[:2000],
                            "number": x.get("numero"), "tomo": x.get("tomo"), "special": f"{x.get('seccion')} sección", "split": "source_document"})
        return bool(rows), out

    def text(self, f, it):
        from urllib.parse import quote
        u = f"{self.B}descargar_pdf.php?archivo={quote(it['pdf'], safe='')}.pdf"
        r = f.get(u)
        k = r.content.find(b"%PDF", 0, 8192)          # server prints an HTML preamble before the PDF bytes
        if r.status_code != 200 or k < 0:
            raise IOError(f"pdf HTTP {r.status_code} (no %PDF)")
        return pdf_text(r.content[k:]), u, None


class Colima:
    """Periódico Oficial del Estado de Colima (periodicooficial.col.gob.mx, static pages). Month index
    p/princi.php?liga=<M>_<YYYY> -> editions p/<ddmmyyyy>/portada.htm; the portada lists the main issue and each
    Suplemento (one PDF each) with its sumario: <div class="titmenu"> headings (DEL GOBIERNO MUNICIPAL / H. AYUNTAMIENTO
    DE X) and <div class="celda"><span> entries. Municipal target entries are cut out of their PDF by title location."""
    key, iso, prefix = "colima", "MX-COL", "06"
    B = "https://periodicooficial.col.gob.mx/p/"
    home = "https://periodicooficial.col.gob.mx/"
    min_interval = 1.5
    floor = "2000-01-01"

    def __init__(self):
        self.months, self._pdf = {}, (None, None)

    def _month(self, f, y, m):
        if (y, m) not in self.months:
            r = f.get(f"{self.B}princi.php?liga={m}_{y}")
            if r.status_code != 200:
                raise IOError(f"month HTTP {r.status_code}")
            self.months = {(y, m): set(re.findall(r"href='(\d{8})/portada\.htm'", r.text))}
        return self.months[(y, m)]

    def day(self, f, d):
        f.allowed(self.home)
        k = f"{d:%d%m%Y}"
        if k not in self._month(f, d.year, d.month):
            return False, []
        r = f.get(f"{self.B}{k}/portada.htm")
        if r.status_code != 200:
            raise IOError(f"portada HTTP {r.status_code}")
        r.encoding = "utf-8"
        h = r.text
        toks = re.finditer(r'<a[^>]+href="([^"]+\.pdf)"|<div class="titmenu">(.*?)</div>|<div class="celda">(.*?)</div>', h, re.S | re.I)
        pubs, cur, head = {}, None, ""
        clean = lambda x: " ".join(html_unescape(re.sub(r"<[^>]+>", " ", x)).split())
        for t in toks:
            if t.group(1):
                cur = t.group(1); pubs.setdefault(cur, []); head = ""
            elif t.group(2) is not None:
                parts = [clean(x) for x in re.split(r"<br\s*/?>", t.group(2)) if clean(x)]
                head = parts[-1] if parts else ""
            elif cur:
                e = clean(t.group(3))
                if e:
                    pubs[cur].append((head, e))
        out = []
        for pdf, ents in pubs.items():
            titles = [e for _, e in ents]
            for i, (hd, e) in enumerate(ents):
                if re.search(r"AYUNTAMIENTO|MUNICIPIO DE", hd, re.I) and TARGET.search(e) and not EXCL.search(e):
                    out.append({"doc_id": f"POECOL-{k}-{pdf.rsplit('/', 1)[-1][:-4]}-{i}", "url": f"{self.B}{k}/{pdf}",
                                "titles": [e], "issuer": re.sub(r"^(H\.\s*)?AYUNTAMIENTO( CONSTITUCIONAL)? DE\s+", "Municipio de ", hd, flags=re.I),
                                "sumario": f"{hd}: {e}", "special": pdf, "all_titles": titles, "idx": i})
        return True, out

    def text(self, f, it):
        if self._pdf[0] != it["url"]:
            r = f.get(it["url"])
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"pdf HTTP {r.status_code}")
            self._pdf = (it["url"], pdf_text(r.content))
        full = self._pdf[1]
        if len(it["all_titles"]) == 1:            # the suplemento holds only this entry
            it["split"] = "whole_publication"
            return full, it["url"], None
        seg = slice_by_titles(full, it["all_titles"]).get(it["idx"])
        if not seg:
            seg = slice_by_titles(full, [t[:30] if len(_nrm(t[:30])) >= 20 else t for t in it["all_titles"]]).get(it["idx"])
        if not seg:
            raise Unlocated("title not located")
        it["split"] = "title_located"
        return seg, it["url"], None


class Queretaro:
    """La Sombra de Arteaga, Periódico Oficial de Querétaro (lasombradearteaga.segobqueretaro.gob.mx, static/PHP).
    getlist.php?p1=<YYYYMMDD> lists the edition's parts (getfile.php?p1=<YYYYMMDD>-NN.pdf). No HTML sumario: the
    SUMARIO is the PDF's first page (layout text: section headings, entries ending in the gazette page number).
    Entries under GOBIERNO MUNICIPAL matching the target criteria are cut by page range [page, next entry's page)
    (gazette page -> PDF page via the 'Pág. N' running heads), then narrowed by title location."""
    key, iso, prefix = "queretaro", "MX-QUE", "22"
    B = "https://lasombradearteaga.segobqueretaro.gob.mx/"
    home = B
    min_interval = 2.0
    floor = "2000-01-01"

    def __init__(self):
        self._pdf, self.years = {}, {}

    def _get_pdf(self, f, u):
        if u not in self._pdf:
            r = f.get(u)
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"pdf HTTP {r.status_code} len={len(r.content)}")
            self._pdf = {u: pdf_text(r.content).split("\f")}
        return self._pdf[u]

    @staticmethod
    def _offset(pages):
        for i, pg in enumerate(pages[:6]):
            m = re.search(r"P[áa]g\.\s*(\d{1,5})", pg[:400]) or re.search(r"P[áa]g\.\s*(\d{1,5})\s*$", pg.strip()[-200:])
            if m:
                return int(m.group(1)) - (i + 1)
        return None

    @staticmethod
    def _sumario(pages):
        txt = "\n".join(pages[:3])
        a = txt.find("SUMARIO")
        if a < 0:
            return []
        ents, buf, head, muni = [], [], "", False
        for line in txt[a + 7:].split("\n"):
            l = line.strip()
            if not l:
                continue
            if re.match(r"(?i)^(INFORMES AL TEL|EN AV\.|https?://|sombradearteaga@)", l) or re.match(r"^\d{1,2} de \w+ de \d{4}\s+LA SOMBRA", l):
                if ents and re.search(r"LA SOMBRA DE ARTEAGA", l):
                    break
                continue
            if re.match(r"^P[áa]g\.\s*\d+\s+PERI", l):
                continue
            m = re.search(r"^(.*?)\s{3,}(\d{2,5})$", line.rstrip())
            if not buf and line.startswith(" " * 8) and not m and l.upper() == l and len(l) < 90:
                head = l; muni = muni or "GOBIERNO MUNICIPAL" in l
                if "AVISOS" in l:
                    break
                continue
            if m:
                buf.append(m.group(1).strip())
                ents.append((head, muni, " ".join(" ".join(buf).split()), int(m.group(2)))); buf = []
            else:
                buf.append(l)
        return ents

    def day(self, f, d):
        f.allowed(self.home)
        if d.year not in self.years:              # year calendar: day cell links -> edition key (YYYYMMNN / YYYYMMDD)
            ry = f.get(f"{self.B}{d.year}.html")
            mp = {}
            if ry.status_code == 200:
                for mi, blk in enumerate(re.split(r'class="month"', ry.text)[1:13], 1):
                    for row in re.findall(r"<tr>(.*?)</tr>", blk, re.S):   # left 7 cells = days, right 7 = edition nos.
                        for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)[:7]:
                            m = re.search(r'getlist\.php\?p1=(\d{8})">(\d{1,2})</a>', c)
                            if m:
                                mp.setdefault((mi, int(m.group(2))), m.group(1))
            self.years = {d.year: mp}
        key = self.years[d.year].get((d.month, d.day))
        if not key:
            return False, []
        r = f.get(f"{self.B}getlist.php?p1={key}")
        if r.status_code != 200:
            raise IOError(f"getlist HTTP {r.status_code}")
        parts = list(dict.fromkeys(re.findall(r'getfile\.php\?p1=(\d{8}-\d+\.pdf)', r.text)))
        out = []
        for pt in parts:
            u = f"{self.B}getfile.php?p1={pt}"
            try:
                pages = self._get_pdf(f, u)
            except IOError as e:
                log.info("queretaro %s: %s", pt, e); continue
            ents, off = self._sumario(pages), self._offset(pages)
            if off is None:
                continue
            for i, (hd, muni, t, gp) in enumerate(ents):
                if muni and TARGET.search(t) and not EXCL.search(t):
                    nxt = next((g for _, _, _, g in ents[i + 1:] if g > gp), None)
                    mm = re.search(r"(?i)municipio de ([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ ]+?)(?:,|\.|\s+Qro|\s+Quer|$)", t)
                    out.append({"doc_id": f"SOMBRA-{pt[:-4]}-p{gp}", "url": u, "titles": [t],
                                "issuer": ("Municipio de " + mm.group(1).strip()) if mm else "", "sumario": f"{hd}: {t}",
                                "special": pt, "page": gp - off, "page_to": (nxt - off) if nxt else gp - off + 60,
                                "all_titles": [x[2] for x in ents], "idx": i, "gpage": gp})
        return bool(parts), out

    def text(self, f, it):
        pages = self._get_pdf(f, it["url"])
        it["page_to"] = min(it["page_to"], len(pages) + 1)
        rng = "\f".join(pages[max(0, it["page"] - 1): max(it["page"], it["page_to"] - 1)])
        seg = slice_by_titles(rng, it["all_titles"]).get(it["idx"])
        if seg and len(seg.strip()) >= MIN_DOC_CHARS:
            it["split"] = "page_range+title_located"; return seg, f"{it['url']}#page={it['page']}", None
        it["split"] = "page_range"
        return "\n".join(pages[it["page"] - 1: max(it["page"], it["page_to"] - 1)]), f"{it['url']}#page={it['page']}", None


class Campeche:
    """Periódico Oficial del Estado de Campeche (periodicooficial.campeche.gob.mx/sipoec, Laravel). Month listing
    documentos?anio=Y&mes=M(&page=N) -> one PDF per section (PO<no><sec><ddmmyyyy>, periodicos/<YYYYMM>/<file>.pdf).
    No sumario: notices are delimited by the right-aligned running head (issuing body / act) on every page; a run of
    pages with the same head is one notice. Municipal (H. Ayuntamiento / Municipio de X) notices whose head or heading
    lines name a target act (reglamento, bando, ...) become records (page range of the run)."""
    key, iso, prefix = "campeche", "MX-CAM", "04"
    B = "https://periodicooficial.campeche.gob.mx/sipoec/public/"
    home = B
    min_interval = 2.0
    floor = "2000-01-01"
    SKIP_HEAD = re.compile(r"(?i)^(San Francisco de Campeche|Cam\.,|P[ÁA]G\.|PERI[ÓO]DICO OFICIAL|\w+ \d{1,2} de \d{4}$|\d+\s*/\s*\d+$)")

    def __init__(self):
        self.months, self._pdf = {}, (None, None)

    def _month(self, f, y, m):
        if (y, m) not in self.months:
            rows, pg = {}, 1
            while pg <= 20:
                r = f.get(f"{self.B}documentos?mes={m:02d}&anio={y}&page={pg}")
                if r.status_code != 200:
                    raise IOError(f"documentos HTTP {r.status_code}")
                got = re.findall(r'data-id="(\d+)"[^>]*>(PO\w+)</a>\s*<a[^>]+>(\d{4}-\d{2}-\d{2})</a>', r.text)
                for did, fn, dt in got:
                    rows.setdefault(dt, {})[fn] = did
                if not got or f"page={pg + 1}" not in r.text.replace("&amp;", "&"):
                    break
                pg += 1
            self.months = {(y, m): rows}
        return self.months[(y, m)]

    MAST = re.compile(r"(?i)(P[ÁA]G\.\s*\d+.*PERI[ÓO]DICO OFICIAL|PERI[ÓO]DICO OFICIAL.*P[ÁA]G\.\s*\d+)")

    def _heads(self, pages):
        """Running head = the 2 lines right after the masthead line ('PÁG. N  PERIÓDICO OFICIAL DEL ESTADO  date'),
        kept only when it repeats on an adjacent page (a real running head, not the first body lines)."""
        cand = []
        for p in pages:
            L = [l.strip() for l in p.split("\n") if l.strip()]
            k = next((i for i, l in enumerate(L[:6]) if self.MAST.search(l)), None)
            hl = [re.sub(r"\s{3,}.*$", "", l) for l in L[k + 1:k + 3]] if k is not None else []
            cand.append((_nrm(" ".join(hl))[:120], " / ".join(hl)))
        out = []
        for i, (key, txt) in enumerate(cand):
            rep = key and ((i > 0 and cand[i - 1][0] == key) or (i + 1 < len(cand) and cand[i + 1][0] == key))
            out.append((key, txt) if rep else ("", ""))
        return out

    def day(self, f, d):
        f.allowed(self.home)
        files = self._month(f, d.year, d.month).get(d.isoformat(), {})
        out = []
        for fn in sorted(files):
            u = f"{self.B}periodicos/{d:%Y%m}/{fn}.pdf"
            try:
                r = f.get(u)
                if r.status_code != 200 or r.content[:4] != b"%PDF":
                    raise IOError(f"pdf HTTP {r.status_code}")
            except IOError as e:
                log.info("campeche %s: %s", fn, e); continue
            pages = pdf_text(r.content).split("\f")
            self._pdf = (u, pages)
            heads = self._heads(pages)
            runs = []
            for i, (k, txt) in enumerate(heads):
                if runs and runs[-1][0] == k:          # same running head, or unheaded after unheaded
                    runs[-1][3] = i
                else:
                    runs.append([k, txt, i, i])
            for k, h, a, b in runs:
                body = "\n".join(pages[a:b + 1])
                bl = [l.strip() for l in body[:5000].split("\n") if l.strip()]
                hd_lines = [(bl[j - 1] if j else "", l) for j, l in enumerate(bl) if 8 < len(l) < 160 and l.upper() == l]
                muni = re.search(r"(?i)ayuntamiento|municipio de", h) or re.search(r"H\.\s*AYU\s*N", body[:2500].upper().replace(" ", " "))
                okt = lambda l: (not re.match(r"(?i)^(\d|ART[ÍI]CULO|[IVXL]+\.|FRACCI)", l) and not EXCL.search(l)
                                 and not re.search(r",\s*\d", l) and (
                                     re.match(r"(?i)^(REGLAMENTO|BANDO|C[ÓO]DIGO\s+(MUNICIPAL|REGLAMENTARIO)|LINEAMIENTOS|ORDENANZA)", l) or
                                     (TARGET.search(l) and re.search(r"(?i)\b(EXPIDE|APRUEBA|REFORMA|MODIFICA|ADICIONA|DEROGA|ABROGA|CREA)", l))))
                tl = h if (h and okt(h.split(" / ")[0])) else next(
                    (l for prev, l in hd_lines if okt(l) and not re.search(r"(?i)(\b(DEL|DE|LA|EL|LOS|LAS|Y|EN)|,)$", prev)), None)
                if not (muni and tl):
                    continue
                mm = re.search(r"(?i)(?:ayuntamiento|municipio)\s+(?:constitucional\s+)?(?:de|del)\s+(?!municipio)([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ ]+?)(?:,|\.|\s+Camp|\s*/|\s{2,}|\n|$)", h + "\n" + body[:2500])
                out.append({"doc_id": f"POECAM-{fn}-p{a + 1}", "url": u, "titles": [tl], "issuer": ("Municipio de " + mm.group(1).strip()) if mm else "",
                            "sumario": f"{h}: {tl}" if h else tl, "special": fn, "page": a + 1, "page_to": b + 2,
                            "split": "running_head" if h else "unheaded_run"})
        return bool(files), out

    def text(self, f, it):
        if self._pdf[0] != it["url"]:
            r = f.get(it["url"])
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"pdf HTTP {r.status_code}")
            self._pdf = (it["url"], pdf_text(r.content).split("\f"))
        pages = self._pdf[1]
        t = "\n".join(pages[it["page"] - 1: it["page_to"] - 1])
        if it.get("split", "").startswith("unheaded"):
            # no running head: start at the title line, end at the next section / edict / notarial notice heading
            j = t.find(it["titles"][0][:40])
            t = t[max(0, j - 1500):] if j > 0 else t
            st0 = (min(j, 1500) if j > 0 else 0) + 500       # markers only after the title
            m = re.search(r"(?m)^\s*(SECCI[ÓO]N\s+(JUDICIAL|LEGISLATIVA|EJECUTIVA|ADMINISTRATIVA)|EDICTO(\s+NOTARIAL)?|AVISO NOTARIAL|"
                          r"PRIMERA PUBLICACI[ÓO]N|CONVOCATORIA|LICITACI[ÓO]N P[ÚU]BLICA)\s*$", t[st0:])
            if m:
                t = t[:st0 + m.start()]
            it["split"] = "unheaded_run+cut" if m else "unheaded_run"
        return t, f"{it['url']}#page={it['page']}", None


class Yucatan:
    """Diario Oficial del Gobierno del Estado de Yucatán (www.yucatan.gob.mx/gobierno/diario_oficial.php?f=<date>).
    Each edition (matutina / vespertina / extra) = one PDF link (/docs/diario_oficial/diarios/<Y>/<date>_<n>.pdf)
    followed by its HTML sumario (<strong> headings: GOBIERNO MUNICIPAL / AYUNTAMIENTO DE X, YUCATÁN; <li> entries).
    Municipal target entries are cut out of the edition PDF by title location."""
    key, iso, prefix = "yucatan", "MX-YUC", "31"
    B = "https://www.yucatan.gob.mx"
    home = B + "/gobierno/diario_oficial.php"
    min_interval = 2.0
    floor = "2000-01-01"

    def __init__(self):
        self._pdf = (None, None)

    def day(self, f, d):
        r = f.get(f"{self.home}?f={d.year}-{d.month:02d}-{d.day}")
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        h = r.text
        blocks = re.findall(r'<a href="(/docs/diario_oficial/diarios/\d{4}/(%s)_\d+\.pdf)" class="pdf"[^>]*>.*?<div class="small sumario">(.*?)</div>' % d.isoformat(), h, re.S)
        out = []
        clean = lambda x: " ".join(html_unescape(re.sub(r"<[^>]+>", " ", x)).split())
        for pdf, _, sm in blocks:
            ents, head, muni = [], "", False
            for t in re.finditer(r"<p[^>]*>(.*?)</p>|<li[^>]*>(.*?)</li>", sm, re.S):
                if t.group(1) is not None:
                    parts = [clean(x) for x in re.findall(r"<strong>(.*?)</strong>", t.group(1), re.S)] or [clean(t.group(1))]
                    for x in parts:
                        if "GOBIERNO MUNICIPAL" in x.upper():
                            muni = True
                        elif re.match(r"(?i)(GOBIERNO DEL ESTADO|PODER |ORGANISMOS|-SUMARIO-)", x):
                            muni = muni and not x.upper().startswith(("GOBIERNO DEL ESTADO", "PODER "))
                        head = x if x else head
                else:
                    e = clean(t.group(2))
                    if e:
                        ents.append((head, muni, e))
            titles = [e for _, _, e in ents]
            for i, (hd, mu, e) in enumerate(ents):
                if (mu or re.search(r"AYUNTAMIENTO|MUNICIPIO DE", hd, re.I)) and TARGET.search(e) and not EXCL.search(e):
                    iss = re.sub(r",\s*YUCAT[ÁA]N\.?\s*$", "", hd, flags=re.I)
                    iss = re.sub(r"(?i)^(H\.\s*)?AYUNTAMIENTO( CONSTITUCIONAL)? DE\s+", "Municipio de ", iss)
                    out.append({"doc_id": f"DOYUC-{pdf.rsplit('/', 1)[-1][:-4]}-{i}", "url": self.B + pdf, "titles": [e], "issuer": iss,
                                "sumario": f"{hd}: {e}", "special": pdf.rsplit('/', 1)[-1], "all_titles": titles, "idx": i})
        return bool(blocks), out

    def text(self, f, it):
        if self._pdf[0] != it["url"]:
            r = f.get(it["url"])
            if r.status_code != 200 or r.content[:4] != b"%PDF":
                raise IOError(f"pdf HTTP {r.status_code}")
            self._pdf = (it["url"], pdf_text(r.content))
        full = self._pdf[1]
        pages = full.split("\f")
        skip = len("\f".join(pages[:1]))
        seg = slice_by_titles(full, it["all_titles"], skip=skip).get(it["idx"])
        if not seg:
            seg = slice_by_titles(full, [t[:30] if len(_nrm(t[:30])) >= 20 else t for t in it["all_titles"]], skip=skip).get(it["idx"])
        if not seg:
            raise Unlocated("title not located")
        it["split"] = "title_located"
        return seg, it["url"], None


ADAPTERS = {"yucatan": Yucatan(), "campeche": Campeche(), "queretaro": Queretaro(), "colima": Colima(), "nayarit": Nayarit(), "morelos": Morelos(), "aguascalientes": Aguascalientes(), "slp": SLP(), "hidalgo": Hidalgo(), "jalisco": Jalisco(), "guanajuato": Guanajuato()}


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


def flush(g, st, buf, unm):
    st["batch"] = st.get("batch", 0) + 1
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    b = f"mx_gaz_{g}-p{st['batch']:05d}-{ts}"
    for pk, rows in buf.items():
        good = [r for r in rows if not S.validate_record(r)]
        bad = [r for r in rows if S.validate_record(r)]
        if bad:
            QUAR.mkdir(parents=True, exist_ok=True)
            with open(QUAR / f"{pk}.{b}.jsonl", "a") as q:
                for r in bad:
                    q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
        if good:
            write(pk, f"{pk}.{b}", good, OUT)
            st["n_docs"] = st.get("n_docs", 0) + len(good)
    if unm:
        write(None, b, unm, UNM)
        st["n_unmatched"] = st.get("n_unmatched", 0) + len(unm)
    for rows in list(buf.values()) + [unm]:
        for r in rows:
            st["done"][r["doc_id"]] = 1
    buf.clear(); unm.clear()


def save(g, st):
    STATE.mkdir(parents=True, exist_ok=True)
    t = STATE / f".{g}.tmp"; t.write_text(json.dumps(st, ensure_ascii=False)); os.replace(t, STATE / f"{g}.json")


def run_state(g, a):
    ad = ADAPTERS[g]
    p = STATE / f"{g}.json"
    st = json.loads(p.read_text()) if p.exists() else {"state": g, "done": {}}
    f = Fetcher(min_interval=max(a.interval, ad.min_interval))
    places = load_places(ad.prefix)
    cur = date.fromisoformat(st.get("cursor") or date.today().isoformat())
    floor = date.fromisoformat(a.floor or ad.floor)
    buf, unm, n_days, misses = {}, [], 0, st.get("misses", 0)
    st["status"] = "running"; save(g, st)
    while cur >= floor:
        try:
            has, items = ad.day(f, cur)
        except CaptchaChallenge as e:
            st.update(status="blocked", reason=f"challenge: {e}"); log.warning("%s blocked (%s) -> stop, not circumvented", g, e); break
        except Blocked as e:
            st.update(status="blocked", reason=str(e)); break
        except Exception as e:  # noqa: BLE001
            st.setdefault("error_days", {})[cur.isoformat()] = f"{type(e).__name__}: {e}"[:160]; has, items = True, []
        misses = 0 if has else misses + 1
        for it in items:
            if it["doc_id"] in st["done"]:
                continue
            try:
                text, src, mid = ad.text(f, it)
            except Unlocated:
                st["n_unlocated"] = st.get("n_unlocated", 0) + 1; st["done"][it["doc_id"]] = "unlocated"; continue
            except Exception as e:  # noqa: BLE001
                st.setdefault("doc_errors", {})[it["doc_id"]] = f"{type(e).__name__}: {e}"[:200]; continue
            title = it["titles"][0]
            place, mname = find_muni(it.get("issuer", ""), places) if it.get("issuer") else (None, None)
            if not place:
                place, mname = find_muni(" ; ".join(it["titles"]), places)
            mname = mname or it.get("issuer")
            npg = (it["page_to"] - it["page"]) if "page" in it else 1
            if len(text.strip()) < 200 or len(text.strip()) < 150 * max(1, npg):     # no / mostly-missing text layer
                SP.append([SP.record(it["doc_id"], S.place_key(place["place_id"], None, "MX") if place else f"mx_gaz_{g}_unmatched", "MX", src,
                                     RP.policy(src, "robots_allowed_rfc9309"))])
                st["n_scanned"] = st.get("n_scanned", 0) + 1; st["done"][it["doc_id"]] = "scanned"; continue
            why = index_like(text, it.get("all_titles") or ())
            if why:
                st[f"n_index_{why}"] = st.get(f"n_index_{why}", 0) + 1; st["done"][it["doc_id"]] = f"index_filtered:{why}"; continue
            dt = "regulation" if re.search(r"reglament|bando|c[oó]digo|lineamiento|ordenamiento", title, re.I) else "ordinance"
            rec = {"place_id": place["place_id"] if place else None, "country_code": "MX", "doc_id": it["doc_id"],
                   "source_platform": f"mx_gazette_{g}", "source_url": src, "doc_type": dt, "language": "es",
                   "html_title": title, "title_native": title, "number": it.get("number"), "published_date": cur.isoformat(),
                   "consolidated": False, "content_format": "pdf_text", "text": text, "retrieved_at": now_utc(),
                   "gazette": g, "gazette_sumario": it["sumario"][:2000], "gazette_titles": it["titles"], "issuer_name": mname,
                   "gazette_tomo": it.get("tomo"), "gazette_edition": it.get("special"), "platform_municipality_id": mid,
                   "platform": f"mx_gazette_{g}", "iso_3166_2": ad.iso, "text_source": "pdf_text", "content_complete": True,
                   "whole_edition": it.get("split", "whole_edition" if "page" not in it else "page_range") == "whole_edition", "split_method": it.get("split") or ("page_range" if "page" in it else "whole_edition"), "pdf_pages": f"{it['page']}-{max(it['page'], it['page_to'] - 1)}" if "page" in it else None, "source_policy": RP.policy(src, "robots_allowed_rfc9309"),
                   "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
            if place:
                rec.update({"place_name": place["place_name"], "qid": place["qid"], "admin_level": "municipality", "inegi_code": place["inegi"]})
            rec = {k: v for k, v in rec.items() if v not in (None, "") or k == "place_id"}
            if place:
                buf.setdefault(S.place_key(place["place_id"], None, "MX"), []).append(rec)
            else:
                unm.append(rec)
        n_days += 1
        cur -= timedelta(days=1)
        if n_days % 7 == 0 or sum(map(len, buf.values())) + len(unm) >= 25:
            flush(g, st, buf, unm); st.update(cursor=cur.isoformat(), misses=misses); save(g, st)
            log.info("%s checkpoint cursor=%s docs=%s unmatched=%s", g, cur, st.get("n_docs", 0), st.get("n_unmatched", 0))
        if misses > 60:
            st["history_start_reached"] = cur.isoformat(); break
        if a.max_days and n_days >= a.max_days:
            break
    flush(g, st, buf, unm)
    if st.get("status") == "running":
        st["status"] = "done_through_floor" if cur < floor or st.get("history_start_reached") else "paused"
    st.update(cursor=cur.isoformat(), misses=misses, requests=st.get("requests", 0) + f.nreq); save(g, st)
    log.info("%s finished status=%s docs=%s unmatched=%s scanned=%s", g, st["status"], st.get("n_docs"), st.get("n_unmatched"), st.get("n_scanned"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", default="guanajuato,jalisco")
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--floor", default=None)
    ap.add_argument("--max-days", type=int, default=0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import threading                       # one thread per state, at most 2 (RAM budget / owner rule)
    gs = a.states.split(",")
    for i in range(0, len(gs), 2):
        ths = [threading.Thread(target=run_state, args=(g, a)) for g in gs[i:i + 2]]
        for t in ths:
            t.start()
        for t in ths:
            t.join()


if __name__ == "__main__":
    main()
