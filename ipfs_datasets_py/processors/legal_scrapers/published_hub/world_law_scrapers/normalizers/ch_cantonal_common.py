import re, json, html as H
LIC = ("Official cantonal legislative texts are not protected by copyright (URG Art. 5 para. 1 lit. a). "
       "Source: the canton's official systematic law collection; only the official publication is legally binding.")
LANG = {"FR": "fr", "VS": "fr", "VD": "fr", "GE": "fr", "JU": "fr", "NE": "fr", "TI": "it"}
def lang_of(c): return LANG.get(c, "de")
def strip(s):
    if not s: return ""
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", s, flags=re.I)
    s = re.sub(r"<sup>(.*?)</sup>", r"\1 ", s, flags=re.S)
    s = H.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()
NUM_RE = re.compile(r"(?:§|Artikel|Articolo|Article|Art\.?|Articolo|Ziff\.|Ch\.|Chiffre)\s*(\d+)\s*([a-z]{1,2}\b|bis|ter|quater|quinquies|sexies|septies|octies|novies|decies)?", re.I)
def base_num(label):
    m = NUM_RE.search(label or "")
    if m: return int(m.group(1)), (m.group(2) or "").lower()
    m = re.search(r"(\d+)", label or "")
    return (int(m.group(1)), "") if m else (None, "")
def numbering_check(labels):
    """labels in document order -> dict with pass flag. Base integers must be non-decreasing and cover 1..max
    (ranges like '12-42' for repealed blocks count as covering)."""
    bases = []; cover = set()
    for l in labels:
        if re.match(r"^\s*(?:§|Artikel\b|Articolo\b|Article\b|Art(?:\.|\b))\s*[A-Za-zÜüÄäÖö]", l or ""): continue  # transitional (T1, Ü1) etc.
        m = re.search(r"(\d+)[a-z]*(?:bis|ter|quater)?\s*[–-]\s*(\d+)", l or "")
        b, _ = base_num(l)
        if b is None: continue
        bases.append(b); cover.add(b)
        if m and int(m.group(2)) > int(m.group(1)) and int(m.group(2)) - int(m.group(1)) < 2000:
            cover.update(range(int(m.group(1)), int(m.group(2)) + 1))
    if not bases: return {"n": 0, "pass": False, "reason": "no_numbered_articles"}
    mono = all(bases[i] <= bases[i + 1] for i in range(len(bases) - 1))
    mx = max(bases); missing = [i for i in range(1, mx + 1) if i not in cover]
    starts1 = min(bases) <= 1
    return {"n": len(labels), "max": mx, "monotonic": mono, "missing": missing[:20], "n_missing": len(missing),
            "starts_at_1": starts1, "pass": mono and not missing and starts1}
def iso(d):
    m = re.fullmatch(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*", d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else (d or "")
def slug(s): return re.sub(r"[^0-9A-Za-z]+", "", s or "") or "x"
def law_id(c, sn): return f"ch-{c.lower()}-{re.sub(r'[\s/]+', '_', sn.strip())}"
def make_law(c, sn, title, text, url, source_type, date, retrieved, n_art, json_path, meta):
    lid = law_id(c, sn); date = iso(date)
    md = {"schema_version": "collection_record.v1", "record_type": "law", "law_identifier": lid, "is_current": True,
          "metadata": dict({"license": LIC, "canton": c, "jurisdiction_level": "cantonal", "systematic_number": sn,
                            "source_name": source_type, "retrieved_at": retrieved}, **meta),
          "article_extraction_status": "ok" if n_art else "no_articles"}
    return {"id": lid, "title": title, "text": text, "source_url": url, "source_type": source_type, "jurisdiction": f"CH-{c}",
            "country": "Switzerland", "language": lang_of(c), "eli": "", "date": date or "", "date_issued": date or "",
            "retrieved_at": retrieved, "license": "public-domain (URG Art. 5)", "law_status": "current", "identifier": sn,
            "official_identifier": f"{c} {sn}", "article_count": int(n_art), "json_path": json_path,
            "metadata_json": json.dumps(md, ensure_ascii=False, separators=(",", ":"))}
def make_articles(c, sn, url, date, arts, backend):
    """arts: list of (label, heading, text, extra_meta)"""
    lid = law_id(c, sn); out = []; seen = {}; date = iso(date)
    for i, (label, heading, text, extra) in enumerate(arts, 1):
        base = f"{lid}-art-{slug(label)}"; k = seen.get(base, 0) + 1; seen[base] = k
        aid = base if k == 1 else f"{base}-{k}"
        md = {"date": date or "", "law_identifier": lid, "language": lang_of(c), "canton": c, "ordinal": i,
              "metadata": dict({"language": lang_of(c), "text_extraction": {"source": "official_cantonal", "backend": backend, "mode": "article"}}, **(extra or {}))}
        title = (label + (" " + heading if heading else "")).strip()
        out.append({"law_id": lid, "id": aid, "title": title, "text": text, "source_url": url, "document_number": label,
                    "article_number": label, "record_type": "article", "metadata_json": json.dumps(md, ensure_ascii=False, separators=(",", ":"))})
    return out
