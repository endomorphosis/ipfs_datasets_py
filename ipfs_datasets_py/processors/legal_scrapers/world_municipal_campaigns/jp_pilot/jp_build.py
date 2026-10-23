"""Japan pilot — harvest + build for Gyosei Reiki-Base 例規集 systems.

Reiki-Base (株式会社ぎょうせい) is the dominant hosted/self-hosted 例規集
platform found in the pilot survey. Structure (verified on Fukuoka):
  <base>/reiki.html                     entry page
  <base>/reiki_taikei/taikei_default.html   systematic index (類 > 章)
  <base>/reiki_taikei/r_taikei_NN_MM.html   chapter page -> ordinance links
  <base>/reiki_honbun/<id>.html             ordinance full text (HTML)
Honbun pages are structured DOM: div.eline lines inside #primary, with
div.article marking each 第N条. Rows = one per article, plus a preamble
row (title/promulgation) and one row per 附則 block.

Checkpointed per municipality into run_manifest.json; parquets in data/.
robots.txt is checked per host before any fetch (build aborts a host
whose robots disallows the reiki paths).
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, drop_empty_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

OUT = Path(__file__).resolve().parent.parent
DATA = OUT / "data"
SCRATCH = OUT / "scratch"
RETRIEVED = "2026-10-14"
JP = get_scheme("JP")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 world-municipal-law-pilot/0.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.5"}
SAMPLE_PER_MUNI = 16  # pilot sample: ordinances per municipality

REGISTRY = {json.loads(l)["code"]: json.loads(l)
            for l in (DATA / "jurisdictions.jsonl").read_text(encoding="utf-8").splitlines()}

# code -> 例規集 root URL (must end with '/'). Two vendor families:
# Reiki-Base (Gyosei, self-hosted) and d1-law (Daiichi Hoki, hosted at
# *.d1-law.com/<slug>/d1w_reiki/). Filled from the survey probes.
MUNICIPALITIES = {
    "40130": "https://www.city.fukuoka.lg.jp/d1w_reiki/",
    "20201": "https://en3-jg.d1-law.com/nagano-city/d1w_reiki/",
    "03201": "https://en3-jg.d1-law.com/morioka/d1w_reiki/",
    "01202": "https://en3-jg.d1-law.com/hakodate/d1w_reiki/",
    "07201": "https://en3-jg.d1-law.com/fukushima/d1w_reiki/",
    "43100": "https://www.city.kumamoto.jp/html/d1w_reiki/",
}

# d1-law text-page URL templates by code: the cloud tenants nest text at
# <id>/<id>_j.html; Kumamoto's self-hosted install nests one level
# deeper (<id>/<id>/<id>_j.html). Default is the cloud pattern.
D1LAW_TEXT_TEMPLATES = {
    "43100": "{id}/{id}/{id}_j.html",
}

ERA = {"明治": 1868, "大正": 1912, "昭和": 1926, "平成": 1989, "令和": 2019}
ERA_RE = re.compile(r"(明治|大正|昭和|平成|令和)(元|\d+)年(\d+)月(\d+)日")
ART_RE = re.compile(r"^第(\d+)条")
SUPPL_RE = re.compile(r"^附\s*則")


def era_to_iso(text):
    m = ERA_RE.search(text or "")
    if not m:
        return ""
    era, y, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
    year = ERA[era] + (1 if y == "元" else int(y)) - 1
    return f"{year:04d}-{mo:02d}-{d:02d}"


class Fetcher:
    def __init__(self):
        self.s = requests.Session()
        self._robots_ok = {}

    def robots_allows(self, url):
        parts = urlparse(url)
        key = (parts.scheme, parts.netloc)
        if key not in self._robots_ok:
            rp = RobotFileParser()
            rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
            try:
                rp.read()
            except Exception:  # noqa: BLE001
                self._robots_ok[key] = True  # unreadable robots: proceed politely
                return True
            self._robots_ok[key] = rp
        rp = self._robots_ok[key]
        if rp is True:
            return True
        return rp.can_fetch(UA, url)

    def get(self, url, cache_path=None, timeout=45, attempts=3):
        if cache_path and cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path.read_bytes()
        if not self.robots_allows(url):
            raise PermissionError(f"robots.txt disallows {url}")
        last = None
        for i in range(attempts):
            try:
                r = self.s.get(url, headers=HEADERS, timeout=timeout)
                if r.status_code == 200 and r.content:
                    if cache_path:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_bytes(r.content)
                    return r.content
                last = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
            time.sleep(2 * (i + 1))
        raise RuntimeError(f"fetch failed {url}: {last}")


def decode(raw):
    for enc in ("utf-8", "shift_jis", "euc_jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def enumerate_corpus(fx, code, base):
    """Return (chapters, docs): chapters = [{title, url}], docs = ordered
    [{honbun_id, name, chapter_title, url}] across all chapter pages."""
    cache = SCRATCH / code
    idx_raw = fx.get(urljoin(base, "reiki_taikei/taikei_default.html"),
                     cache / "taikei_default.html")
    soup = BeautifulSoup(decode(idx_raw), "html.parser")
    chapters = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"r_taikei_\d+_\d+\.html$", href):
            chapters.append({"title": a.get_text(strip=True),
                             "url": urljoin(base + "reiki_taikei/", href)})
    docs, seen = [], set()
    for ch in chapters:
        raw = fx.get(ch["url"], cache / Path(ch["url"]).name)
        s2 = BeautifulSoup(decode(raw), "html.parser")
        for a in s2.find_all("a", href=True):
            m = re.search(r"reiki_honbun/([A-Za-z0-9]+)\.html$", a["href"])
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                docs.append({"honbun_id": m.group(1),
                             "name": a.get_text(strip=True),
                             "chapter_title": ch["title"],
                             "url": urljoin(base, f"reiki_honbun/{m.group(1)}.html")})
        time.sleep(0.5)
    return chapters, docs


# Explicit family overrides: Kumamoto runs the Daiichi Hoki layout
# self-hosted on its own domain, so the host-name heuristic misses it.
FAMILY_OVERRIDES = {"43100": "d1law"}


def family_of(base, code=None):
    if code in FAMILY_OVERRIDES:
        return FAMILY_OVERRIDES[code]
    return "d1law" if "d1-law.com" in base else "reikibase"


def enumerate_d1law(fx, code, base):
    text_tmpl = D1LAW_TEXT_TEMPLATES.get(code, "{id}/{id}_j.html")
    """Daiichi Hoki system: mokuji_bunya_index.html links bunya category /
    chapter pages; chapters list ordinances via
    javascript:OpenResDataWin('<doc_id>'); text at <id>/<id>_j.html."""
    cache = SCRATCH / code
    idx_raw = fx.get(urljoin(base, "mokuji_bunya_index.html"),
                     cache / "mokuji_bunya_index.html")
    idx_text = decode(idx_raw)
    soup = BeautifulSoup(idx_text, "html.parser")
    pages = []
    for a in soup.find_all("a", href=True):
        if re.search(r"bunya_\d+\.html$", a["href"]):
            pages.append({"title": a.get_text(" ", strip=True),
                          "url": urljoin(base, a["href"])})
    if not pages:
        # Older D1W generation (Kumamoto): JS tree menu — chapter pages
        # are bunya_<id>.html synthesized from ViewMokujiList('<id>').
        for a in soup.find_all("a", href=True):
            m = re.search(r"ViewMokujiList\('(\d+)'", a["href"])
            if m:
                pages.append({"title": a.get_text(" ", strip=True),
                              "url": urljoin(base, f"bunya_{m.group(1)}.html")})
    docs, seen = [], set()
    for pg in pages:
        raw = fx.get(pg["url"], cache / Path(pg["url"]).name)
        text = decode(raw)
        # Two-arg generation: OpenResDataWin('<hno>','<kno>') opens
        # <hno>/<kno>/<kno>.html — kno is the current document id.
        two = re.finditer(r"OpenResDataWin\('([A-Za-z0-9_]+)','([A-Za-z0-9_]+)'\)[^>]*>([^<]+)", text)
        matched = False
        for m in two:
            matched = True
            hno, doc_id, doc_name = m.group(1), m.group(2), m.group(3).strip()
            if doc_id not in seen:
                seen.add(doc_id)
                docs.append({"honbun_id": doc_id, "name": doc_name.lstrip("○"),
                             "chapter_title": pg["title"],
                             "url": urljoin(base, f"{hno}/{doc_id}/{doc_id}_j.html")})
        if matched:
            time.sleep(0.5)
            continue
        for m in re.finditer(r"OpenResDataWin\('([A-Za-z0-9_]+)'\)[^>]*>([^<]+)", text):
            doc_id, doc_name = m.group(1), m.group(2).strip()
            if doc_id not in seen:
                seen.add(doc_id)
                docs.append({"honbun_id": doc_id, "name": doc_name,
                             "chapter_title": pg["title"],
                             "url": urljoin(base, text_tmpl.format(id=doc_id))})
        time.sleep(0.5)
    return pages, docs


ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def parse_d1law(html_text):
    """Split a d1-law _j.html text page (flat div.danraku-normal stream)
    into preamble / article / suppl units, same shape as parse_honbun."""
    soup = BeautifulSoup(html_text, "html.parser")
    holder = soup.select_one("div.USER-SET-STYLE") or soup.body
    divs = holder.select("div.danraku-normal") if holder else []
    if not divs and holder:
        divs = holder.find_all("div", recursive=False)
    meta = {"title": "", "promulgated_iso": ""}
    units = []
    cur = {"key": "preamble", "label": "題名・公布", "parts": []}
    pending_heads = []
    art_no = 0
    suppl_no = 0

    def flush():
        if cur["parts"]:
            units.append({"key": cur["key"], "label": cur["label"],
                          "html": "\n".join(cur["parts"])})

    for dv in divs:
        text = dv.get_text(" ", strip=True)
        norm = text.translate(ZEN)
        outer = str(dv)
        am = re.match(r"^第(\d+)条", norm)
        if am:
            art_no = int(am.group(1))
            flush()
            heading = pending_heads[0][0] if pending_heads else ""
            label = f"第{art_no}条 {heading}".strip()
            cur = {"key": f"a{art_no}", "label": label,
                   "parts": [h for _, h in pending_heads] + [outer]}
            pending_heads = []
            continue
        if SUPPL_RE.match(norm.replace(" ", "")) and len(norm) < 40:
            flush()
            suppl_no += 1
            cur = {"key": f"suppl{suppl_no}", "label": "附則", "parts": [outer]}
            pending_heads = []
            continue
        if re.match(r"^（.+）$", norm) and len(norm) <= 60:
            pending_heads.append((norm, outer))
            continue
        if not meta["title"] and text.startswith("○"):
            meta["title"] = text.lstrip("○").strip()
        if not meta["promulgated_iso"]:
            meta["promulgated_iso"] = era_to_iso(norm)
        cur["parts"].append(outer)
    flush()
    if not meta["title"] and soup.title:
        meta["title"] = soup.title.get_text(strip=True).lstrip("○").strip()
    return meta, units


def sample_docs(docs, n=SAMPLE_PER_MUNI):
    """Deterministic spread: up to 4 from the first chapter (which is
    usually short 市制 notices), then evenly spaced picks across the
    whole corpus until n are chosen."""
    if len(docs) <= n:
        return docs
    first_ch = docs[0]["chapter_title"]
    chosen = [d for d in docs if d["chapter_title"] == first_ch][:4]
    chosen_ids = {d["honbun_id"] for d in chosen}
    rest = [d for d in docs if d["honbun_id"] not in chosen_ids]
    need = n - len(chosen)
    step = max(1, len(rest) // need)
    chosen += rest[::step][:need]
    return chosen


def parse_honbun(html_text):
    """Split a Reiki-Base honbun page into units:
    [preamble] + [article N]* + [suppl K]*. Returns (meta, units) where
    units = [{key, label, html}] and meta = {title, promulgated_iso}."""
    soup = BeautifulSoup(html_text, "html.parser")
    primary = soup.select_one("#primary") or soup.body
    lines = primary.select("div.eline") if primary else []
    meta = {"title": "", "promulgated_iso": ""}
    units = []
    cur = {"key": "preamble", "label": "題名・公布", "parts": []}
    pending_heads = []
    art_no = 0
    suppl_no = 0

    def flush():
        if cur["parts"]:
            units.append({"key": cur["key"], "label": cur["label"],
                          "html": "\n".join(cur["parts"])})

    for ln in lines:
        text = ln.get_text(" ", strip=True)
        outer = str(ln)
        article_div = ln.select_one("div.article")
        head = ln.select_one("p.s-head")
        head_text = head.get_text(" ", strip=True) if head else ""
        if article_div is not None:
            m = ART_RE.search(text)
            art_no = int(m.group(1)) if m else art_no + 1
            flush()
            title_p = article_div.select_one("p.title")
            heading = title_p.get_text(" ", strip=True) if title_p else ""
            label = f"第{art_no}条 {heading}".strip()
            cur = {"key": f"a{art_no}", "label": label,
                   "parts": pending_heads + [outer]}
            pending_heads = []
            continue
        if head is not None and SUPPL_RE.match(head_text.replace(" ", "")):
            flush()
            suppl_no += 1
            cur = {"key": f"suppl{suppl_no}", "label": "附則", "parts": [outer]}
            pending_heads = []
            continue
        if head is not None and re.match(r"^第.+[章編]", head_text):
            pending_heads.append(outer)
            continue
        # metadata capture from the preamble lines
        if ln.select_one("p.title-irregular") is not None and not meta["title"]:
            meta["title"] = text.lstrip("○").strip()
        if ln.select_one("p.date") is not None and not meta["promulgated_iso"]:
            meta["promulgated_iso"] = era_to_iso(text)
        cur["parts"].append(outer)
    flush()
    if not meta["title"] and soup.title:
        meta["title"] = soup.title.get_text(strip=True).lstrip("○").strip()
    return meta, units


def build_municipality(fx, code, base):
    reg = REGISTRY[code]
    name = reg["name"]
    fam = family_of(base, code)
    if fam == "d1law":
        chapters, docs = enumerate_d1law(fx, code, base)
        parse = parse_d1law
    else:
        chapters, docs = enumerate_corpus(fx, code, base)
        parse = parse_honbun
    chosen = sample_docs(docs)
    print(f"{code} {name}: corpus {len(docs)} ordinances / {len(chapters)} chapters; "
          f"sampling {len(chosen)}", flush=True)
    rows = []
    doc_meta = []
    for d in chosen:
        raw = fx.get(d["url"], SCRATCH / code / "honbun" / f"{d['honbun_id']}.html")
        meta, units = parse(decode(raw))
        title = meta["title"] or d["name"]
        path = f"{d['chapter_title']} / {title}"
        for u in units:
            rows.append(make_row(
                jurisdiction_id=code, jurisdiction_name=name, country="JP",
                doc_id=f"{d['honbun_id']}-{u['key']}",
                regeling_id=d["honbun_id"], regeling_work_id=d["honbun_id"],
                title=title, structural_path=path, node_label=u["label"],
                body_html=u["html"], source_url=d["url"],
                date_effective=meta["promulgated_iso"], retrieved=RETRIEVED,
            ))
        doc_meta.append({"honbun_id": d["honbun_id"], "name": title,
                         "chapter": d["chapter_title"], "units": len(units),
                         "promulgated": meta["promulgated_iso"]})
        time.sleep(0.5)
    rows = drop_empty_rows(finalize_rows(rows))
    table = rows_to_table(rows)
    errs = validate_table(table, jurisdiction_id=code, jurisdiction_name=name,
                          country="JP")
    report = validation_report(table, jurisdiction_id=code,
                               jurisdiction_name=name, country="JP")
    dest = DATA / JP.file_name(code)
    write_html_parquet(dest, table)
    write_validation_report(DATA / f"{code}_validation.json", report)
    back = read_html_parquet(dest)
    errs2 = validate_table(back, jurisdiction_id=code, jurisdiction_name=name,
                           country="JP")
    print(f"{code} {name}: rows {table.num_rows} valid={not errs} "
          f"reread_valid={not errs2} errs={errs + errs2}", flush=True)
    return {"name": name, "base": base, "family": fam, "corpus_docs": len(docs),
            "chapters": len(chapters), "sampled_docs": len(chosen),
            "docs": doc_meta, "rows": table.num_rows,
            "valid": not errs and not errs2, "errors": errs + errs2}


def main():
    only = sys.argv[1:] or list(MUNICIPALITIES)
    manifest_path = OUT / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"municipalities": {}}
    fx = Fetcher()
    for code in only:
        code = JP.normalize(code)
        try:
            res = build_municipality(fx, code, MUNICIPALITIES[code])
            manifest["municipalities"][code] = res
        except Exception as e:  # noqa: BLE001
            manifest["municipalities"][code] = {"error": f"{type(e).__name__}: {e}"}
            print(code, "FAILED", e, flush=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print("manifest updated")


if __name__ == "__main__":
    main()
