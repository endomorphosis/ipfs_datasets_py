"""Post-process JP forms crawl (idempotent): title = the anchor's own title attribute (official label), category = page breadcrumb label, court tier from category; reject only leaflets/manuals/guides/checklists
-> data/jp/jp_rejected_brochures.jsonl. Re-downloads kept files if missing."""
import sys, collections, hashlib, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
from bs4 import BeautifulSoup
BAD = re.compile(r"リーフレット|パンフレット|マニュアル|手引|ガイド|チェックリスト|Q&A|Ｑ＆Ａ|よくある|冊子|ポスター|動画|白書|のしおり|案内", re.I)
def court_for(cat, ix):
    if re.search(r"家事|少年|人事|家庭|後見|補助|保佐|成年", cat): return "jp-family"
    if re.search(r"簡易|少額|督促|支払督促", cat): return "jp-summary"
    return "jp-district"
def main():
    cur = [json.loads(l) for l in open(f"{ROOT}/data/jp/jp_forms.jsonl")]; old_rej = [json.loads(l) for l in open(f"{ROOT}/data/jp/jp_rejected_brochures.jsonl")] if os.path.exists(f"{ROOT}/data/jp/jp_rejected_brochures.jsonl") else []
    byurl = {r["source_url"]: r for r in cur}; idx = {r["source_url"]: r["index_url"] for r in cur}
    ixs = sorted(set(idx.values()))
    ctx = {}; cat = {}
    for ix in ixs:
        b, u, pol = polite_get(ix, delay=2)
        if not b: continue
        s = BeautifulSoup(b, "html.parser"); lab = s.select_one(".c-breadcrumb-item[aria-current] .c-breadcrumb-label"); c = lab.get_text(strip=True) if lab else ""
        h = ""
        for a in s.find_all("a", href=True):
            if not re.search(r"\.(pdf|docx?|xlsx?)", a["href"], re.I): continue
            href = urllib.parse.urljoin(ix, a["href"]); t = re.sub(r"\s+", " ", a.get("title") or "").strip()
            if not t:
                st = a.find_previous("strong"); t = (st.get_text(" ", strip=True) + " " + a.get_text(" ", strip=True)) if st else a.get_text(" ", strip=True)
            ctx[href] = re.sub(r"\s+", " ", t); cat[href] = (c, ix)
    # candidates: current + previously rejected (some wrongly)
    allurls = list(dict.fromkeys(list(byurl) + [r["source_url"] for r in old_rej])); out = []; rej = []
    for href in allurls:
        t = ctx.get(href) or (byurl[href]["title"][:100] if href in byurl else href.rsplit("/", 1)[-1]); c, ix = cat.get(href, ("", idx.get(href, "")))
        if BAD.search(t) or BAD.search(href.rsplit("/", 1)[-1]): rej.append(dict(title=t, source_url=href, reason="leaflet/manual/guide/checklist (not a fillable form)")); r = byurl.get(href)

        else:
            r = byurl.get(href)
            if r is None or not os.path.exists(f"{ROOT}/{r['pdf_path']}"):
                d, eu, p2 = polite_get(href, delay=2.0, binary=True)
                if not d or len(d) < 500: continue
                ext = re.search(r"\.(pdf|docx?|xlsx?)", href, re.I).group(1).lower(); sh = hashlib.sha256(d).hexdigest(); path = f"forms/jp/{sh}.{ext}"; open(f"{ROOT}/{path}", "wb").write(d)
                r = dict(form_id=f"jp-{sh[:16]}", court_id=None, jurisdiction="JP", form_number=None, title=t, category=c, language="ja", file_format=ext, pdf_path=path, pdf_sha256=sh, file_bytes=len(d), source_url=eu, index_url=ix,
                         license="Supreme Court of Japan (courts.go.jp) published court forms/templates (書式); reuse per site terms", site_policy=p2, retrieved_at=NOW())
            r["title"] = t[:200]; r["category"] = c or r.get("category"); r["court_id"] = court_for(c, ix)
            if "記載例" in t: r["category"] = (r["category"] or "") + " (filled-in example)"
            out.append(r)
    keep = {o["pdf_path"] for o in out}
    for f in os.listdir(f"{ROOT}/forms/jp"):
        if f"forms/jp/{f}" not in keep: os.remove(f"{ROOT}/forms/jp/{f}")
    seen = set(); out = [o for o in out if not (o["pdf_sha256"] in seen or seen.add(o["pdf_sha256"]))]
    wjl(f"{ROOT}/data/jp/jp_forms.jsonl", out); wjl(f"{ROOT}/data/jp/jp_rejected_brochures.jsonl", rej); print("JP forms", len(out), "rejected", len(rej)); print(collections.Counter(o["court_id"] for o in out))
    for o in out[:12]: print(" ", o["file_format"], o["category"], "|", o["title"][:60])
    for o in rej: print(" rej", o["title"][:60])
if __name__ == "__main__": main()
