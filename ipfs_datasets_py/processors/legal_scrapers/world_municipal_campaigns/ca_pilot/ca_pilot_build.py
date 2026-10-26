"""Canada municipal-law pilot — route survey + bounded harvest.

First Canada work in the world municipal-law program (goal_16f788ee16e8).
Sample: 5 municipalities x ~4 consolidated bylaw documents across 4
provinces, normalized to the shared world_municipal 19-column schema.
Jurisdiction IDs: Statistics Canada SGC census subdivision (CSD) codes,
registered this pilot as world_municipal SgcScheme (CA) in the repo
working tree (local only, no commit/push; suite 37 -> 38 tests, all pass).

Route verification (live, 2026-10-12, from this VM's egress):
- CivicWeb (*.civicweb.net, iCompass): robots.txt wildcard group is
  "User-agent: * / Disallow: /" (486 UA groups; only named bots get
  partial allowances). EXCLUDED on robots grounds — same posture class
  as NL/KOOP and ID/Denpasar in earlier pilots. Not fetched.
- eScribe (pub-*.escribemeetings.com): robots.txt is 33 bytes blocking
  only PetalBot -> documents are robots-allowed, and the portal itself
  loads (200). BUT the document endpoint (filestream.ashx) sits behind
  a Cloudflare bot check: direct fetch returns a 403 "Verifying your
  browser - eScribe" JS-challenge page; a portal-session fetch hangs
  (60 s read timeout); the portal sets a __cf_bm cookie. No Wayback
  snapshots exist for the sampled DocumentIds. Document download is
  therefore egress-blocked; Kawartha Lakes is NOT harvested in this
  pilot (evidence in the pilot report).
- City of Winnipeg (winnipeg.ca): HTTP 403 F5 rejection page for every
  path incl. robots.txt from this egress. EXCLUDED (egress wall).
- Ville de Quebec reglements host (reglements.ville.quebec.qc.ca,
  Cyberlex): robots disallows /fr/showPdf + /en/showPdf (the PDF
  endpoints), /fr/search, /fr/result etc. The generated URLs use
  /fr/ShowPdf (capital S); harvesting on a case-sensitivity technicality
  against evident intent is not defensible under program posture.
  EXCLUDED on robots grounds.
- ottawa.ca: Incapsula bot-wall (robots.txt itself returns an
  Incapsula challenge page). EXCLUDED (egress wall).
- Harvested routes (all robots-verified with urllib.robotparser
  against the exact document URLs): Toronto Municipal Code chapter
  PDFs (toronto.ca/legdocs/municode/), Surrey bylaw PDFs
  (surrey.ca/sites/default/files/bylaws/), Halifax by-law PDFs
  (halifax.ca/sites/default/files/documents/city-hall/
  legislation-by-laws/, discovered from each by-law's HTML page),
  Gatineau reglement PDFs (gatineau.ca/docs/...; robots Crawl-delay 10
  honoured with 11 s pacing; only .pdf paths used - /docs/*.htm(l)
  disallows do not cover the bylaw PDFs).

Attribution gate (fail-don't-emit): each document's extracted text must
contain the municipality's marker string; each document must split
into >= 2 sections; empty fragments are dropped, never emitted.
"""

import html as html_mod
import json
import re
import sys
import time
from pathlib import Path

import pymupdf
import requests

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

OUT = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/ca_pilot"
RAW = OUT / "data" / "raw"
DATA = OUT / "data"
RAW.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) world-municipal-law-pilot/0.1"}
RETRIEVED = "2026-10-12"
CA = get_scheme("CA")
SESSION = requests.Session()
SESSION.headers.update(UA)

# per-host pacing (seconds): gatineau robots Crawl-delay is 10 -> 11 s.
HOST_DELAY = {"www.gatineau.ca": 11.0}
DEFAULT_DELAY = 2.0
_last = {}


def fetch(url: str, dest: Path | None = None) -> bytes:
    host = re.sub(r"^https?://", "", url).split("/")[0]
    wait = HOST_DELAY.get(host, DEFAULT_DELAY)
    last = _last.get(host, 0.0)
    dt = time.time() - last
    if dt < wait:
        time.sleep(wait - dt)
    try:
        r = SESSION.get(url, timeout=90)
    except requests.exceptions.Timeout:
        time.sleep(5)
        r = SESSION.get(url, timeout=120)
    _last[host] = time.time()
    r.raise_for_status()
    if dest is not None:
        dest.write_bytes(r.content)
    return r.content


def pdf_text(path: Path) -> str:
    doc = pymupdf.open(path)
    pages = [doc[p].get_text() for p in range(doc.page_count)]
    doc.close()
    return "\n".join(pages)


# ---------------------------------------------------------------- text cleanup
def clean_lines(text: str, drop_res: list[re.Pattern]) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if any(r.search(s) for r in drop_res):
            continue
        out.append(s)
    return out


def join_fragment(lines: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


# ---------------------------------------------------------------- splitters
def split_fragments(lines: list[str], heading_re: re.Pattern):
    """Split lines at heading lines. Returns [(label, [body lines])]."""
    frags: list[tuple[str, list[str]]] = []
    cur_label = ""
    cur: list[str] = []
    for line in lines:
        if heading_re.match(line):
            frags.append((cur_label, cur))
            cur_label = line
            cur = []
        else:
            cur.append(line)
    frags.append((cur_label, cur))
    return frags


def merge_tiny(frags, min_chars=40):
    """Merge fragments whose body is < min_chars into the previous one."""
    out: list[tuple[str, str]] = []
    for label, body_lines in frags:
        body = join_fragment(body_lines)
        if out and len(body) < min_chars:
            out[-1] = (out[-1][0], (out[-1][1] + " " + (label + " " if label else "") + body).strip())
        else:
            out.append((label, body))
    return out


TORONTO_DROP = [
    re.compile(r"^TORONTO MUNICIPAL CODE$"),
    re.compile(r"^CHAPTER \d+,"),
    re.compile(r"^\d+-\d+$"),  # folio like 349-1
    re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}$"),
    re.compile(r"^Chapter \d+$"),
]
SECTION_RE = re.compile(r"^§\s*(\d+)-(\d+(?:\.\d+)?)\.\s*(.*)$")


def toronto_sections(text: str):
    """Split a Municipal Code chapter at section headings.

    Chapters open with a table of contents listing every section, and
    compilation chapters (e.g. 545, Licensing) repeat a mini-ToC at each
    ARTICLE. Strategy: split at every section heading, group fragments
    by section number, keep the LONGEST body per section (the real
    text, not a ToC stub), in first-occurrence order. Fragments whose
    longest body is a < 25-char stub are dropped unless they are a
    genuine "(Reserved)" placeholder."""
    raw_lines = [l.strip() for l in text.splitlines()]
    frags = split_fragments([l for l in raw_lines if l], SECTION_RE)
    best: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    for label, body_lines in frags:
        m = SECTION_RE.match(label)
        if not m:
            continue
        sec = f"{m.group(1)}-{m.group(2)}"
        body = join_fragment(body_lines)
        if sec not in best:
            order.append(sec)
            best[sec] = (m.group(3).strip(), body)
        elif len(body) > len(best[sec][1]):
            best[sec] = (m.group(3).strip(), body)
    out = []
    for sec in order:
        heading, body = best[sec]
        if len(body) < 25 and "reserved" not in body.lower():
            continue  # ToC stub / linearization fragment, not a provision
        out.append((sec, heading, body, ""))
    return out


NUM_ONLY_RE = re.compile(r"^(\d+)\.$")
NUM_HEAD_RE = re.compile(r"^(\d+)\.\s+(\S.*)$")
LETTER_RE = re.compile(r"^([A-Z])\.$")
CAPS_RE = re.compile(r"^[A-Z][A-Z0-9 ,;:'&()\-/]{3,}$")


DECIMAL_ONLY_RE = re.compile(r"^(\d+\.\d+)\.?$")


def numbered_sections(lines, caps_headings=False, decimal=False):
    """Split at standalone 'N.' / 'N.N' lines (Surrey modern / Gatineau
    articles / Halifax clauses). With caps_headings, an ALL-CAPS line
    immediately preceding a number line becomes that fragment's heading
    (and is not duplicated into the previous fragment's body)."""
    frags = []
    cur_label, cur = "", []
    heading = ""
    pending = ""
    n = len(lines)
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < n else ""
        is_num_next = bool(NUM_ONLY_RE.match(nxt) or NUM_HEAD_RE.match(nxt)
                           or (decimal and DECIMAL_ONLY_RE.match(nxt)))
        if caps_headings and CAPS_RE.match(line) and len(line) > 3 and is_num_next:
            pending = line
            continue
        m = (NUM_ONLY_RE.match(line) or NUM_HEAD_RE.match(line)
             or (DECIMAL_ONLY_RE.match(line) if decimal else None))
        if m:
            frags.append((cur_label, cur, heading))
            cur_label = line
            cur = []
            heading = pending
            pending = ""
        else:
            cur.append(line)
    frags.append((cur_label, cur, heading))
    out = []
    for label, body_lines, heading in frags:
        if not label:
            continue
        out.append((label, heading, join_fragment(body_lines)))
    return out


def lettered_sections(lines):
    """Surrey legacy format: 'A.' + ALL-CAPS title, numbered clauses inside."""
    frags = []
    cur_label, cur = "", []
    for line in lines:
        if LETTER_RE.match(line):
            frags.append((cur_label, cur))
            cur_label = line
            cur = []
        else:
            cur.append(line)
    frags.append((cur_label, cur))
    out = []
    for label, body_lines in frags:
        if not label:
            continue
        title = body_lines[0] if body_lines and CAPS_RE.match(body_lines[0]) else ""
        out.append((label, title, join_fragment(body_lines[1:] if title else body_lines)))
    return out


# ---------------------------------------------------------------- doc builders
def para_html(text: str) -> str:
    return f"<p>{html_mod.escape(text)}</p>"


def build_rows(jid, jname, docs_out, doc_meta, sections, source_url, xml_url,
               date_modified="", manifest=None):
    """sections: [(sec_label_for_id, node_label, body, structural_path)]

    A document is recorded (and its rows returned) only when it yields
    >= 2 non-empty section rows; otherwise it is fail-closed dropped
    and noted in the manifest."""
    rows = []
    for sec_id, node_label, body, path in sections:
        if not body.strip():
            continue
        rows.append(make_row(
            jurisdiction_id=jid, jurisdiction_name=jname, country="Canada",
            doc_id=f"{doc_meta['slug']}-{sec_id}",
            regeling_id=doc_meta["regeling_id"],
            regeling_work_id=doc_meta["work_id"],
            title=doc_meta["title"],
            structural_path=path,
            node_label=node_label,
            body_html=para_html(body),
            source_url=source_url, xml_url=xml_url,
            date_effective=doc_meta.get("date_effective", ""),
            date_modified=date_modified,
            retrieved=RETRIEVED,
        ))
    if len(rows) < 2:
        if manifest is not None:
            manifest.setdefault("dropped_docs", []).append(
                {"jurisdiction": jid, "doc": doc_meta["regeling_id"],
                 "reason": f"only {len(rows)} section rows after split (gate: >= 2)",
                 "source_url": source_url})
        return []
    docs_out.append({"regeling_id": doc_meta["regeling_id"], "title": doc_meta["title"],
                     "sections": len(rows), "source_url": source_url})
    return rows


# ---------------------------------------------------------------- Toronto
def do_toronto(manifest):
    jid, jname = "3520005", "Toronto"
    chapters = [217, 349, 545, 813]
    all_rows, docs = [], []
    for ch in chapters:
        url = f"https://www.toronto.ca/legdocs/municode/1184_{ch:03d}.pdf"
        path = RAW / f"toronto_{ch}.pdf"
        if not path.exists():
            fetch(url, path)
        text = pdf_text(path)
        assert "TORONTO MUNICIPAL CODE" in text, f"attribution failed ch {ch}"
        m = re.search(rf"CHAPTER {ch},?\s+([A-Z][A-Z /&;'-]+)", text)
        ch_title = (m.group(1).strip().title() if m else f"Chapter {ch}")
        secs = toronto_sections(text)
        meta = {"slug": f"chapter-{ch}", "regeling_id": f"chapter-{ch}",
                "work_id": "toronto-municipal-code",
                "title": f"Toronto Municipal Code, Chapter {ch}: {ch_title}"}
        rows = build_rows(jid, jname, docs, meta,
                          [(f"s{sec}", f"§ {sec}. {head}", body,
                            f"Chapter {ch}: {ch_title} > § {sec}")
                           for sec, head, body, _art in secs],
                          "https://www.toronto.ca/legdocs/bylaws/lawmcode.htm", url,
                          manifest=manifest)
        all_rows += rows
        manifest["docs_detail"].append({"jurisdiction": jid, "doc": meta["regeling_id"],
                                        "sections": len(rows), "pages": pymupdf.open(path).page_count})
    return jid, jname, "City of Toronto — Toronto Municipal Code (consolidated chapters)", all_rows, docs


# ---------------------------------------------------------------- Surrey
SURREY_DROP = [
    re.compile(r"^CITY OF SURREY$"),
    re.compile(r"^BY-?LAW NO\.?\s*\d+$", re.I),
    re.compile(r"^\d+$"),  # page folios
    re.compile(r"^- \d+ -$"),
]

def do_surrey(manifest):
    jid, jname = "5915004", "Surrey"
    files = {"7044": "BYL_Reg_7044.pdf", "13007": "BYL_reg_13007.pdf",
             "16100": "BYL_reg_16100.pdf", "19105": "BYL_reg_19105.pdf"}
    cached = {"7044": "surrey_Reg_7044.pdf", "13007": "surrey_reg_13007.pdf",
              "16100": "surrey_reg_16100.pdf", "19105": "surrey_reg_19105.pdf"}
    all_rows, docs = [], []
    for num, fname in files.items():
        url = f"https://www.surrey.ca/sites/default/files/bylaws/{fname}"
        path = RAW / cached[num]
        if not path.exists():
            fetch(url, path)
        text = pdf_text(path)
        assert "City of Surrey" in text or "CITY OF SURREY" in text, f"attribution failed {num}"
        # Title: only trust a title string that names THIS bylaw's number
        # (consolidations quote other bylaws in repeal/reference clauses).
        title = None
        first_pages = "\n".join(text.split("\n")[:120])
        tm = re.search(rf"([A-Z][A-Za-z ,&'()\-]{{4,80}}By-?law,? \d{{4}},? No\. {num})", first_pages)
        if tm:
            title = tm.group(1).strip()
        if not title:
            tm = re.search(rf'"([^"\n]{{8,100}}No\. {num}[^"\n]*)"', text)
            if tm:
                title = tm.group(1).strip()
        if not title:
            tm = re.search(r"A by-law to ([^\n.]{5,90})", text, re.I)
            title = (f"City of Surrey By-law No. {num} — a by-law to {tm.group(1).strip()}"
                     if tm else f"City of Surrey By-law No. {num}")
        lines = clean_lines(text, SURREY_DROP)
        # Strategy: standalone-number sections; if the numbering restarts
        # (>= 2 restarts — legacy bylaws restart clause numbers inside
        # lettered parts), prefer the lettered-part split.
        raw_secs = numbered_sections(lines)
        labels = [int(m.group(1)) for lbl, _h, _b in raw_secs
                  if (m := NUM_ONLY_RE.match(lbl))]
        restarts = sum(1 for a, b in zip(labels, labels[1:]) if b <= a)
        secs = [(lbl, "", body) for lbl, _h, body in raw_secs if len(body) >= 40]
        strategy = "numbered"
        if restarts >= 2:
            lsecs = [(lbl, ttl, body) for lbl, ttl, body in lettered_sections(lines) if len(body) >= 40]
            if len(lsecs) >= 2:
                secs, strategy = lsecs, "lettered"
        if len(secs) < 2:
            lsecs = [(lbl, ttl, body) for lbl, ttl, body in lettered_sections(lines) if len(body) >= 40]
            if len(lsecs) >= 2:
                secs, strategy = lsecs, "lettered"
        meta = {"slug": f"bylaw-{num}", "regeling_id": num,
                "work_id": "surrey-bylaws", "title": title}
        rows = build_rows(jid, jname, docs, meta,
                          [(f"s{sec[0].rstrip('.')}", f"Section {sec[0].rstrip('.')}" + (f" {sec[1]}" if sec[1] else ""), sec[2],
                            f"By-law No. {num} > {sec[0].rstrip('.')}")
                           for sec in secs],
                          "https://www.surrey.ca/city-government/bylaws", url,
                          manifest=manifest)
        all_rows += rows
        manifest["docs_detail"].append({"jurisdiction": jid, "doc": num, "strategy": strategy,
                                        "sections": len(rows), "pages": pymupdf.open(path).page_count})
    return jid, jname, "City of Surrey — consolidated by-laws (bespoke PDF library)", all_rows, docs


# ---------------------------------------------------------------- Halifax
HALIFAX_DROP = [
    re.compile(r"^HALIFAX REGIONAL MUNICIPALITY$"),
    re.compile(r"^By-law [A-Z]-\d+.*Page \d+ of \d+$"),
    re.compile(r"^\d+$"),
]

def do_halifax(manifest):
    jid, jname = "1209034", "Halifax"
    codes = ["A-100", "C-300", "N-200", "P-400"]
    all_rows, docs = [], []
    for code in codes:
        page_url = f"https://www.halifax.ca/city-hall/legislation-by-laws/by-law-{code.lower()}"
        html_bytes = fetch(page_url)
        m = re.search(rb'href="(https://www\.halifax\.ca/sites/default/files/documents/city-hall/legislation-by-laws/[^"]+\.pdf)"', html_bytes)
        assert m, f"no PDF link on {page_url}"
        url = m.group(1).decode()
        path = RAW / f"halifax_{code}.pdf"
        if not path.exists():
            fetch(url, path)
        text = pdf_text(path)
        assert "Halifax Regional Municipality" in text, f"attribution failed {code}"
        tm = re.search(r"RESPECTING\s+([A-Z][A-Z0-9 ,;:'&()\-/]+)", text)
        topic = (tm.group(1).strip().title() if tm else "")
        title = f"Halifax By-law {code}" + (f" respecting {topic}" if topic else "")
        lines = clean_lines(text, HALIFAX_DROP)
        secs = numbered_sections(lines, caps_headings=True, decimal=True)
        secs = [s for s in secs if len(s[2]) >= 40]
        meta = {"slug": f"bylaw-{code.lower()}", "regeling_id": code,
                "work_id": "halifax-bylaws", "title": title}
        rows = build_rows(jid, jname, docs, meta,
                          [(f"s{s[0].rstrip('.')}", (s[1].title() if s[1] else f"Section {s[0].rstrip('.')}"), s[2],
                            f"By-law {code} > {s[0].rstrip('.')}")
                           for s in secs],
                          page_url, url, manifest=manifest)
        all_rows += rows
        manifest["docs_detail"].append({"jurisdiction": jid, "doc": code,
                                        "sections": len(rows), "pages": pymupdf.open(path).page_count})
    return jid, jname, "Halifax Regional Municipality — by-laws (bespoke PDF library)", all_rows, docs


# ---------------------------------------------------------------- Gatineau
GATINEAU_DROP = [
    re.compile(r"^Ville de Gatineau$"),
    re.compile(r"^Règlement .* numéro \d+-\d+$"),
    re.compile(r"^Le présent document n'a aucune valeur légale"),
    re.compile(r"^apportées depuis son adoption\."),
    re.compile(r"^toutefois aucune garantie"),
    re.compile(r"^\d+-\d+$"),  # chapter-page folio (1-1, 3-2)
    re.compile(r"^(i|ii|iii|iv|v|vi|vii|viii|ix|x)$"),  # front-matter folios
    re.compile(r"\.{6,}"),  # ToC dot leaders
]
FR_MONTHS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5,
             "juin": 6, "juillet": 7, "août": 8, "septembre": 9, "octobre": 10,
             "novembre": 11, "décembre": 12}

def do_gatineau(manifest):
    jid, jname = "2481017", "Gatineau"
    docs_spec = [
        ("503-2005", "Règlement de lotissement",
         "https://www.gatineau.ca/docs/guichet_municipal/reglements_municipaux/reglements_urbanisme/docs/R-503_lotissement/R_503-2005.pdf"),
        ("506-2005", "Règlement relatif aux usages conditionnels",
         "https://www.gatineau.ca/docs/guichet_municipal/reglements_municipaux/reglements_urbanisme/docs/R-506_usages_conditionnels/R_506-2005.pdf"),
        ("507-2005", "Règlement sur les projets particuliers de construction, de modification ou d'occupation d'un immeuble",
         "https://www.gatineau.ca/docs/guichet_municipal/reglements_municipaux/reglements_urbanisme/docs/R-507_ppc/R_507-2005.pdf"),
    ]
    all_rows, docs = [], []
    cached = {"503-2005": "gatineau_503.pdf", "506-2005": "gatineau_506.pdf",
              "507-2005": "gatineau_507.pdf"}
    for num, short_title, url in docs_spec:
        path = RAW / cached[num]
        if not path.exists():
            fetch(url, path)
        text = pdf_text(path)
        assert "Ville de Gatineau" in text, f"attribution failed {num}"
        comp_dates = []
        for dm in re.finditer(r"Compilation administrative au (\d{1,2}) (\w+) (\d{4})", text):
            if dm.group(2).lower() in FR_MONTHS:
                comp_dates.append(f"{dm.group(3)}-{FR_MONTHS[dm.group(2).lower()]:02d}-{int(dm.group(1)):02d}")
        date_mod = max(comp_dates) if comp_dates else ""
        lines = clean_lines(text, GATINEAU_DROP)
        secs = numbered_sections(lines)
        built = []
        for lbl, _h, body in secs:
            if len(body) < 40:
                continue
            # node label: article number + leading CAPS title words of the body
            m2 = re.match(r"^([A-ZÀ-Þ][A-ZÀ-Þ0-9 ,;:'&()\-/]{3,60}?)\s+(?=[A-ZÀ-Þa-zà-ÿ«])", body)
            node = f"Article {lbl.rstrip('.')}" + (f" — {m2.group(1).strip().title()}" if m2 else "")
            built.append((f"art-{lbl.rstrip('.')}", node, body,
                          f"Règlement {num} > Article {lbl.rstrip('.')}"))
        meta = {"slug": f"reglement-{num}", "regeling_id": num,
                "work_id": "gatineau-reglements-urbanisme",
                "title": f"{short_title} numéro {num} (Ville de Gatineau)"}
        rows = build_rows(jid, jname, docs, meta, built,
                          "https://www.gatineau.ca/portail/default.aspx?p=guichet_municipal/reglements_municipaux/reglements_urbanisme",
                          url, date_modified=date_mod, manifest=manifest)
        all_rows += rows
        manifest["docs_detail"].append({"jurisdiction": jid, "doc": num,
                                        "sections": len(rows), "pages": pymupdf.open(path).page_count,
                                        "date_modified": date_mod})
    return jid, jname, "Ville de Gatineau — règlements d'urbanisme (compilations administratives, French)", all_rows, docs


# ---------------------------------------------------------------- main
def main():
    manifest = {"pilot": "canada", "retrieved": RETRIEVED, "docs_detail": [],
                "municipalities": {}}
    jurisdictions = []
    for fn in (do_toronto, do_surrey, do_halifax, do_gatineau):
        jid, jname, route, rows, docs = fn(manifest)
        jid = CA.normalize(jid)
        rows = finalize_rows(rows)
        rows = [r for r in rows if r["text"].strip() and r["html"].strip()]
        table = rows_to_table(rows)
        report = validation_report(table, jurisdiction_id=jid,
                                   jurisdiction_name=jname, country="Canada")
        fpath = DATA / CA.file_name(jid)
        write_html_parquet(fpath, table)
        back = read_html_parquet(fpath)
        report2 = validation_report(back, jurisdiction_id=jid,
                                    jurisdiction_name=jname, country="Canada")
        assert report["valid"] and report2["valid"], f"{jid} INVALID: {report['errors']} / {report2['errors']}"
        write_validation_report(DATA / f"{jid}_validation.json", report2)
        manifest["municipalities"][jid] = {
            "name": jname, "route": route, "docs": docs,
            "rows": back.num_rows, "valid": True,
            "file": f"data/{CA.file_name(jid)}",
        }
        jurisdictions.append({
            "jurisdiction_id": jid, "jurisdiction_name": jname,
            "country": "Canada", "id_scheme": "Statistics Canada SGC census subdivision code",
            "province": {"3520005": "Ontario", "5915004": "British Columbia",
                         "1209034": "Nova Scotia", "2481017": "Quebec"}[jid],
            # document language, verified from the harvested texts:
            # Toronto/Surrey/Halifax by-laws are English; Gatineau
            # reglements are French (compilations administratives).
            "language": {"3520005": "en", "5915004": "en",
                         "1209034": "en", "2481017": "fr"}[jid],
            "csd_type": {"3520005": "C", "5915004": "CY",
                         "1209034": "RGM", "2481017": "V"}[jid],
            "route": route, "pilot": True,
            "docs": len(docs), "rows": back.num_rows,
        })
        print(f"{jid} {jname}: {len(docs)} docs, {back.num_rows} rows, VALID")
    (OUT / "jurisdictions.jsonl").write_text(
        "".join(json.dumps(j, ensure_ascii=False) + "\n" for j in jurisdictions), encoding="utf-8")
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    total = sum(m["rows"] for m in manifest["municipalities"].values())
    print(f"TOTAL: {len(jurisdictions)} municipalities, {total} rows")


if __name__ == "__main__":
    main()
