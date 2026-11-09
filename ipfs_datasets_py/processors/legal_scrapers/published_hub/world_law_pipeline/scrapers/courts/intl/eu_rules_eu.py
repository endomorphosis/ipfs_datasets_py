"""EU-level procedural rules + EU standard forms from EUR-Lex (official, reuse Decision 2011/833/EU, CC-BY 4.0).
EUR-Lex returns a WAF challenge to non-browser clients (HTTP 202, empty) -> we read the Internet Archive copies (web.archive.org/web/2026id_/<url>); no challenge bypass.
-> data/eu/eu_rules.jsonl, data/eu/eu_forms.jsonl, forms/eu/<sha256>.pdf"""
import sys, hashlib, re, os, json
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get, RAW
from lxml import html as lh
def ws(s): return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()
# (rule_set_id, name, CELEX, kind) kind: rop = court rules of procedure; reg = procedural instrument with standard forms
INST = [("eu-cjeu-rop", "Rules of Procedure of the Court of Justice (as published OJ L 265, 29.9.2012; later amendments not applied)", "32012Q0929(01)", "rop"), ("eu-gc-rop", "Rules of Procedure of the General Court (as published OJ L 105, 23.4.2015; later amendments not applied)", "32015Q0423(01)", "rop"),
 ("eu-brussels-ia", "Regulation (EU) No 1215/2012 (Brussels I recast)", "32012R1215", "reg"), ("eu-escp", "Regulation (EC) No 861/2007 European Small Claims Procedure", "32007R0861", "reg"),
 ("eu-epo", "Regulation (EC) No 1896/2006 European Order for Payment", "32006R1896", "reg"), ("eu-eeo", "Regulation (EC) No 805/2004 European Enforcement Order", "32004R0805", "reg"),
 ("eu-eapo", "Regulation (EU) No 655/2014 European Account Preservation Order", "32014R0655", "reg"), ("eu-service", "Regulation (EU) 2020/1784 Service of documents", "32020R1784", "reg"),
 ("eu-evidence", "Regulation (EU) 2020/1783 Taking of evidence", "32020R1783", "reg"), ("eu-brussels-iib", "Regulation (EU) 2019/1111 Brussels IIb", "32019R1111", "reg"),
 ("eu-maintenance", "Regulation (EC) No 4/2009 Maintenance", "32009R0004", "reg"), ("eu-succession", "Regulation (EU) No 650/2012 Succession", "32012R0650", "reg"),
 ("eu-succession-forms", "Implementing Regulation (EU) No 1329/2014 Succession forms", "32014R1329", "reg"), ("eu-insolvency", "Regulation (EU) 2015/848 Insolvency proceedings", "32015R0848", "reg"),
 ("eu-legal-aid", "Directive 2003/8/EC Legal aid in cross-border disputes", "32003L0008", "reg"), ("eu-public-docs", "Regulation (EU) 2016/1191 Public documents", "32016R1191", "reg"),
 ("eu-matrimonial", "Regulation (EU) 2016/1103 Matrimonial property regimes", "32016R1103", "reg"), ("eu-partnerships", "Regulation (EU) 2016/1104 Registered partnerships", "32016R1104", "reg"),
 ("eu-ecr", "Regulation (EU) No 606/2013 Mutual recognition of protection measures", "32013R0606", "reg")]
WB = "https://web.archive.org/web/2026id_/"
def fetch(celex, fmt):
    u = f"https://eur-lex.europa.eu/legal-content/EN/TXT/{fmt}/?uri=CELEX:{celex}"
    p = f"{RAW}/intl_eu_{re.sub(r'[^A-Za-z0-9]', '_', celex)}.{fmt.lower()}"
    if os.path.exists(p): return open(p, "rb").read(), u
    b, eu, pol = polite_get(WB + u.replace("(", "%28").replace(")", "%29"), delay=3.0, binary=True, maxbytes=80_000_000)
    if not b or len(b) < 5000 or (fmt == "PDF" and b[:4] != b"%PDF"): return None, u
    open(p, "wb").write(b); return b, u
def rules_from(sid, name, celex, raw, src):
    d = lh.fromstring(raw); sha = hashlib.sha256(raw).hexdigest(); out = []
    for dv in d.iter("div"):
        i = dv.get("id") or ""
        if not (re.fullmatch(r"art_[\dA-Za-z]+", i) or re.fullmatch(r"anx_[\dA-Za-z]+", i)): continue
        if (dv.get("class") or "") != "eli-subdivision" and not i.startswith("anx"): continue
        num_el = dv.xpath(".//p[contains(@class,'ti-art') and not(contains(@class,'sti'))]|.//p[contains(@class,'doc-ti')]")
        stis = dv.xpath(".//div[@class='eli-title']/p[contains(@class,'sti-art')]")
        num = ws(num_el[0].text_content()) if num_el else (("Article " + i[4:]) if i.startswith("art") else ("Annex " + i[4:]))
        title = ws(stis[0].text_content()) if stis else None
        txt = []
        for p in dv.iter("p", "td"):
            c = p.get("class") or ""
            if "ti-art" in c or ("doc-ti" in c and p is num_el[0:1] ): continue
            t = ws(p.text_content())
            if t and t not in txt: txt.append(t)
        text = ws(" ".join(t for t in txt if t not in (num, title)))
        if len(text) < 20: continue
        out.append(dict(rule_id=f"{sid}:{num}", rule_set_id=sid, court_id=None, jurisdiction="EU", rule_set=name, rule_number=num, title=title, text=text, effective_date=None, pdf_path=None, pdf_sha256=None, source_sha256=sha,
                        source_url=src, site_policy="archive_wayback", retrieved_at=NOW(), license="CC-BY-4.0 (EU legal act reuse, Decision 2011/833/EU; (c) European Union)", language="en"))
    if not out:  # legacy EUR-Lex markup: flat <p class=ti-art|sti-art|normal> sequence
        cur = None; ps = d.xpath("//p|//table//td")
        for p in ps:
            c = p.get("class") or ""; t = ws(p.text_content())
            if not t: continue
            if re.search(r"(^|[- ])ti-art", c) and "sti" not in c and re.match(r"^(Article|ANNEX|Annex)\b", t):
                cur = dict(rid=t, title=None, parts=[]); out.append(cur)
            elif cur is not None and "sti-art" in c and cur["title"] is None: cur["title"] = t
            elif cur is not None and ("normal" in c or "tbl" in c or "ti-grseq" in c or "doc-ti" in c or p.tag == "td"): 
                if t not in cur["parts"]: cur["parts"].append(t)
        out = [dict(rule_id=f"{sid}:{o['rid']}", rule_set_id=sid, court_id=None, jurisdiction="EU", rule_set=name, rule_number=o["rid"], title=o["title"], text=ws(" ".join(o["parts"])), effective_date=None, pdf_path=None, pdf_sha256=None, source_sha256=sha,
                    source_url=src, site_policy="archive_wayback", retrieved_at=NOW(), license="CC-BY-4.0 (EU legal act reuse, Decision 2011/833/EU; (c) European Union)", language="en") for o in out if len(" ".join(o["parts"])) >= 20]
    # dedupe numbering collisions
    seen = {}
    for r in out:
        k = r["rule_id"]; seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1: r["rule_id"] += f"~{seen[k]}"
    return out
def main():
    rules = []; forms = []; os.makedirs(f"{ROOT}/forms/eu", exist_ok=True)
    for sid, name, celex, kind in INST:
        raw, src = fetch(celex, "HTML")
        if not raw: print("MISS html", sid, celex, flush=True); continue
        r = rules_from(sid, name, celex, raw, src); rules += r; nan = sum(1 for x in r if x["rule_number"].lower().startswith(("annex", "form")))
        print(sid, len(r), "annex", nan, flush=True)
        pdf, psrc = fetch(celex, "PDF")
        if pdf:
            sha = hashlib.sha256(pdf).hexdigest(); path = f"forms/eu/{sha}.pdf"
            if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(pdf)
            txt = ""
            try:
                import subprocess; txt = subprocess.run(["pdftotext", "-layout", f"{ROOT}/{path}", "-"], capture_output=True, text=True).stdout
            except Exception: pass
            heads = []
            for m in re.finditer(r"^\s*((?:STANDARD\s+)?FORM\s+[A-Z0-9]{1,3}\b[^\n]{0,80}|ANNEX\s+[IVX]+\s*[^\n]{0,80}|CERTIFICATE[^\n]{0,80}|FORMULAIRE[^\n]{0,60})\s*$", txt, re.M):
                h = ws(m.group(1))
                if h.upper() not in {x.upper() for x in heads} and len(heads) < 60: heads.append(h)
            base = dict(court_id=None, jurisdiction="EU", language="en", file_format="pdf", pdf_path=path, pdf_sha256=sha, file_bytes=len(pdf), source_url=psrc, index_url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
                        license="CC-BY-4.0 (EU legal act reuse, Decision 2011/833/EU)", site_policy="archive_wayback", retrieved_at=NOW(), category=name)
            forms.append(dict(form_id=f"eu-{celex}-full", form_number=f"CELEX:{celex}", title=f"{name} - full text with annexes/standard forms", **base))
            for h in heads:
                forms.append(dict(form_id=f"eu-{celex}-{slug(h)[:40]}", form_number=h[:60], title=f"{name} - {h}", **base))
            print("  pdf", len(pdf), "heads", len(heads), flush=True)
    wjl(f"{ROOT}/data/eu/eu_rules.jsonl", rules); wjl(f"{ROOT}/data/eu/eu_forms.jsonl", forms); print("EU rules", len(rules), "forms", len(forms))
if __name__ == "__main__": main()
