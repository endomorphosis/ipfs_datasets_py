"""Rechtspraak.nl (Dutch judiciary) forms, procedural regulations and declaration forms: crawl /voor-advocaten-en-juristen/reglementen-procedures-en-formulieren/** (depth<=2),
download linked documents (pdf/docx/doc/xlsx) -> forms/nl/<sha256>.<ext>; metadata -> data/nl/nl_forms.jsonl. Resumable. Crawl delay 2 s."""
import sys, hashlib, urllib.parse, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
from bs4 import BeautifulSoup
BASE = "https://www.rechtspraak.nl"; START = BASE + "/voor-advocaten-en-juristen/reglementen-procedures-en-formulieren"
def main(maxpages=60, maxdocs=400):
    os.makedirs(f"{ROOT}/forms/nl", exist_ok=True); out = []; seen_pages = set(); q = [(START, 0, None)]; docs = {}; pg = 0
    while q and pg < maxpages:
        u, d, cat = q.pop(0)
        if u in seen_pages: continue
        seen_pages.add(u); b, eu, pol = polite_get(u, delay=2.0)
        if not b: continue
        pg += 1; s = BeautifulSoup(b.decode("utf-8", "replace"), "html.parser"); cat = cat or u.rsplit("/", 1)[-1]
        for a in s.find_all("a", href=True):
            h = urllib.parse.urljoin(u, a["href"]).split("#")[0]; t = a.get_text(" ", strip=True)
            if re.search(r"\.(pdf|docx?|xlsx?|rtf)(\?|$)", h, re.I) and "/binaries/" in h:
                docs.setdefault(h, (t, u, cat, pol))
            elif h.startswith(START) and d < 2 and h not in seen_pages and "?" not in h: q.append((h, d + 1, h.rsplit("/", 1)[-1]))
        print("page", pg, u[-60:], len(docs), flush=True)
    for i, (h, (t, src, cat, pol)) in enumerate(docs.items()):
        if i >= maxdocs: break
        b, eu, p2 = polite_get(h, delay=2.0, binary=True, maxbytes=40_000_000)
        if not b or len(b) < 500: continue
        ext = re.search(r"\.(pdf|docx?|xlsx?|rtf)", h, re.I).group(1).lower(); sha = hashlib.sha256(b).hexdigest(); path = f"forms/nl/{sha}.{ext}"
        if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(b)
        out.append(dict(form_id=f"nl-rechtspraak-{sha[:16]}", court_id=None, jurisdiction="NL", form_number=None, title=re.sub(r"\s*\((pdf|docx?|xlsx?),? [\d,.]+ \w+\)\s*$", "", t) or h.rsplit("/", 1)[-1], category=cat, language="nl", file_format=ext, pdf_path=path, pdf_sha256=sha, file_bytes=len(b),
                        source_url=eu, index_url=src, license="rechtspraak.nl published court forms (public judiciary documents; reuse per site terms)", site_policy=p2, retrieved_at=NOW()))
        if len(out) % 20 == 0: wjl(f"{ROOT}/data/nl/nl_forms.jsonl", out)
    wjl(f"{ROOT}/data/nl/nl_forms.jsonl", out); print("NL forms", len(out), collections.Counter(o["file_format"] for o in out))
if __name__ == "__main__": main()
