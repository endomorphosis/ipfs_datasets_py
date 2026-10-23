"""flk.npc.gov.cn (国家法律法规数据库) from web archives only.

flk detail pages archive as JavaScript shells, so text comes from the archived file host wb.flk.npc.gov.cn:
  * WORD/<id32>.docx and PDF/<id32>.pdf downloads              -> full text (docx XML / pdftotext)
  * <cat>/html/<x>/<sha40>/0/text/<n>.json reader pages        -> glyph runs per page, re-assembled by line;
    info.json gives the page count; usually only some pages were archived -> content_complete=false
Categories: flfg 法律, xffl 宪法, xzfg 行政法规, sfjs 司法解释, dfxfg 地方性法规 (province-level -> iso:CN-XX adm1;
city / autonomous-prefecture regulations -> municipal lanes, skipped).
"""
import io, json, re, zipfile
from xml.etree import ElementTree as ET

from places import cn_province_level

CATS = {"flfg": "statute", "xffl": "statute", "xzfg": "regulation", "sfjs": "regulation", "dfxfg": "regulation"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(body: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter(W + "p"):
        t = "".join((n.text or "") if n.tag == W + "t" else ("\t" if n.tag == W + "tab" else "")
                    for n in p.iter() if n.tag in (W + "t", W + "tab"))
        paras.append(t)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(paras)).strip()


def reader_page_text(body: bytes) -> str:
    arr = json.loads(body)
    lines = {}
    for e in arr:
        c = e.get("coord") or [0, 0]
        lines.setdefault(c[0], []).append((c[1], "".join(x.get("text", "") for x in e.get("code", []))))
    out = []
    for ln in sorted(lines):
        s = "".join(t for _, t in sorted(lines[ln])).strip()
        if s and not re.fullmatch(r"[—\-－–\s]*\d+[—\-－–\s]*", s):   # page numbers
            out.append(s)
    return "\n".join(out)


def join_cn_lines(text: str) -> str:
    """Reader pages wrap lines visually; re-join wrapped lines inside paragraphs (keep 第X条/章 starts)."""
    out = []
    for l in text.splitlines():
        if out and not re.match(r"^(第[一二三四五六七八九十百零〇\d]+[条章节编]|（|\(|[一二三四五六七八九十]+、)", l) \
                and not re.search(r"[。：；！？」）)]$", out[-1]) and len(out[-1]) >= 18:
            out[-1] += l
        else:
            out.append(l)
    return "\n".join(out)


def title_from_text(text: str) -> str:
    ls = [l.strip() for l in text.splitlines() if l.strip()]
    t = ""
    for l in ls[:4]:
        if re.match(r"^[（(]", l):
            break
        t += l
        if re.search(r"(法|条例|决定|规定|办法|解释|细则|规则|决议|宪法|修正案|批复)$", t):
            break
    return t[:300]


def place_for(cat: str, title: str):
    if cat != "dfxfg":
        return ("iso:CN", "中国", None, "country")
    r = cn_province_level(title)
    if isinstance(r, tuple):
        return (f"iso:{r[0]}", r[1], r[0], "adm1")
    return r  # 'municipal' or None


def build(runner, r, doc):
    """Custom builder for CN_flk candidates. Returns (record_without_provenance, why, fmt, extra)."""
    key = r["key"]                      # 'cat/WORD/id32.docx' | 'cat/PDF/id32.pdf' | 'cat/reader/sha40'
    cat, kind = key.split("/")[:2]
    kind = kind.lower()
    fx = runner.fx
    incomplete = None
    if kind == "reader":
        sha = key.split("/")[2]
        base = f"wb.flk.npc.gov.cn/{cat}/html/{sha[0]}/{sha}/0/"
        caps = fx.wb_captures(base, "prefix", status200=True, collapse="urlkey")
        pages, count = {}, None
        for c in sorted(caps, key=lambda c: c.timestamp, reverse=True):
            m = re.search(r"/0/text/(\d+)\.json", c.original_url)
            if "info.json" in c.original_url and count is None:
                try:
                    count = int(json.loads(fx.fetch_capture(c).body).get("count") or 0) or None
                except Exception:
                    pass
            elif m and int(m.group(1)) not in pages:
                try:
                    pages[int(m.group(1))] = reader_page_text(fx.fetch_capture(c).body)
                except Exception:
                    pass
        if not pages:
            return None, "reader_no_text_pages", None, None
        text = join_cn_lines("\n".join(pages[i] for i in sorted(pages)))
        have = sorted(pages)
        if count is None or len(have) < count or have != list(range(len(have))):
            incomplete = f"flk_reader_pages:{','.join(map(str, have))}/{count or '?'}"
        fmt = "pdf_text"   # reader pages are the rendered PDF/OFD text layer
    elif kind == "word":
        try:
            text = docx_text(doc.body)
        except Exception as e:
            return None, f"docx_error:{type(e).__name__}", None, None
        fmt = "docx_text"
    else:
        from run_archive import pdf_text
        text = pdf_text(doc.body)
        fmt = "pdf_text"
    text = text.strip()
    title = title_from_text(text)
    return {"text": text, "title": title, "cat": cat, "doc_type": CATS.get(cat, "statute"),
            "place": place_for(cat, title)}, "ok", fmt, incomplete
