"""Depth-pass-5 rules for AU (WA Rules of the Supreme Court 1971 from legislation.wa.gov.au HTML; SA Uniform Civil Rules 2020 from Courts SA compilation PDF) and CA provinces (see CA builders below).
usage: row_rules8.py <KEY>.. ; keys: AU_WA AU_SA ... -> appends to data/<cc>/<cc>_rules.jsonl (+crosswalk), replacing the same rule_set_id."""
import sys, json, os, re, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_rules7 import *
def ws2(s): return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()
def rr(sid, cc, name, jur, num, title, text, url, sh, pol, lic, lang="en", eff=None):
    r = row(sid, cc, name, num, text, url, sh, pol, lic, lang, eff, title); r["jurisdiction"] = jur; return r
def au_wa():
    p = f"{RAW}/au2/wa_rscp.txt"; L = open(p).read().split("\n"); sh = sha(f"{RAW}/au2/wa_rscp.htm"); L = L[1326:]
    cur = None; num = None; title = None; buf = []; out = []
    url = "https://www.legislation.wa.gov.au/legislation/statutes.nsf/RedirectURL?OpenAgent&query=mrdoc_49048.htm"; name = "Rules of the Supreme Court 1971 (WA), consolidated 09-am0-00"
    def flush():
        if cur and num and buf:
            t = ws2(" ".join(b for b in buf if not re.match(r"^\[.*(amended|inserted|deleted|repealed|substituted|Heading|Gazette).*\]$", b)))
            if len(t) > 10: out.append(rr("au-wa-rsc", "AU", name, "AU-WA", f"O.{cur} r.{num}", title, t[:12000], url, sh, "robots_unknown:no_robots_txt (legislation.wa.gov.au robots.txt returns 404; official Government of Western Australia legislation database, HTML consolidated version)", "Western Australian legislation; Crown copyright, reuse permitted under the State Law Publisher terms (CC BY 4.0 for the legislation database)"))
    for ln in L:
        m = re.match(r"^Order (\d+[A-Z]{0,3}) — (.+)$", ln)
        if m: flush(); cur = m.group(1); num = None; buf = []; continue
        if re.match(r"^(Division|Subdivision|Part|Appendix|Schedule) ", ln) and len(ln) < 120 and cur: 
            if re.match(r"^(Appendix|Schedule)", ln): flush(); cur = None; num = None; buf = []
            continue
        m = re.match(r"^(\d{1,3}[A-Z]{0,3})\.([A-Z\[].{0,110})$", ln)
        if m and cur and not re.search(r"[.;:,]$", m.group(2)): flush(); num = m.group(1); title = m.group(2).strip(); buf = []; continue
        if cur and num: buf.append(ln)
    flush(); seen = {}; res = []
    for r in out:
        if r["rule_id"] in seen: continue
        seen[r["rule_id"]] = 1; res.append(r)
    print("au-wa-rsc", len(res)); return res, xwalk("AU", "au-wa-rsc", name, ["au-wa-supreme-court"], url, "rule set applies to this court (Supreme Court of Western Australia, civil jurisdiction)")
def au_sa():
    p = f"{RAW}/au2/sa_ucr.txt"; t = open(p, errors="ignore").read(); sh = sha(f"{RAW}/au2/sa_ucr.pdf")
    i = [m.start() for m in re.finditer(r"1\.1—Title", t)]
    t = t[i[1]:] if len(i) > 1 else t
    t = "\n".join(l for l in t.split("\n") if not re.search(r"^Uniform Civil Rules 2020\s*$|^Current to .*Amending Rules|^\s+[ivxlc\d]+\s*$|^\s*—?\s*Chapter \d+|^\s{20,}\d+\s*$", l))
    lst = seq_split(t, re.compile(r"(?m)^[ \t]{0,4}(\d{1,3}\.\d{1,3}[A-Z]?)—([^\n.]{3,110}?)[ \t]*$"), lambda m: m.group(1))
    mx = 0; keep = []
    for k, b in lst:
        n = int(k.split(".")[0])
        if n < mx: continue
        mx = n; keep.append((k, b))
    lst = keep
    url = "https://www.courts.sa.gov.au/wp-content/uploads/wp-download-manager-files/court-rules/08-uniform-civil-rules/Uniform%20Civil%20Rules%202020.pdf"; name = "Uniform Civil Rules 2020 (SA), current to 15 September 2026"
    rows = [rr("au-sa-ucr", "AU", name, "AU-SA", f"r.{k}", None, b, url, sh, "allowed_by_robots (courts.sa.gov.au robots.txt disallows only plugins, admin, login, list/judgment paths and /download/; Courts Administration Authority consolidated compilation, informational; the gazetted version is the official text)", "South Australian legislation; Crown copyright, CC BY 4.0 (SA Government open data licence)") for k, b in lst]
    print("au-sa-ucr", len(rows)); return rows, xwalk("AU", "au-sa-ucr", name, ["au-sa-supreme-court", "au-sa-intermediate-court", "au-sa-lower-court"], url, "rule set applies to this court (Supreme, District and Magistrates Courts of South Australia)")
B.update(AU_WA=au_wa, AU_SA=au_sa)

CRAW = f"{RAW}/ca2"
def _ca(sid, name, cc, jur, nums_rows, url, sh, pol, lic, courts, basis):
    rows = [rr(sid, "CA", name, jur, n, t, b, url, sh, pol, lic) for n, t, b in nums_rows]
    print(sid, len(rows)); return rows, xwalk("CA", sid, name, courts, url, basis)
def _split_lines(t, rx, titlefn=None, drop=None):
    L = t.split("\n")
    if drop: L = [l for l in L if not drop(l)]
    idx = [(i, rx.match(l)) for i, l in enumerate(L)]; idx = [(i, m) for i, m in idx if m]
    out = []; seen = set()
    for j, (i, m) in enumerate(idx):
        e = idx[j + 1][0] if j + 1 < len(idx) else len(L); k = m.group(1)
        if k in seen: continue
        body = ws2(" ".join([L[i][m.end():]] + L[i + 1:e]))
        if len(body) < 10: continue
        seen.add(k); out.append((k, titlefn(L, i, m) if titlefn else (m.group(2).strip() if m.lastindex and m.lastindex >= 2 else None), body[:12000]))
    return out
def ca_ns():
    t = open(f"{CRAW}/ns_cpr.txt", errors="ignore").read(); sh = sha(f"{CRAW}/ns_cpr.pdf")
    rx = re.compile(r"^(\d{1,3}\.\d{2}[A-Z]?)[ \t]+([A-Z][^\n]{2,95}[^\s.;,:])$")
    r = _split_lines(t, rx, drop=lambda l: re.match(r"^\s*-\d+-\s*$", l) or "Nova Scotia Civil Procedure Rules" in l)
    r = [(f"Rule {k}", ti, b) for k, ti, b in r]
    return _ca("ca-ns-cpr", "Nova Scotia Civil Procedure Rules (official consolidation of 19 June 2026)", "ca", "CA-NS", r, "https://www.courts.ns.ca/sites/default/files/rules/CPR%20Rules/Official_Consolidated_Rules_Jun_19_2026.pdf", sh, "allowed_by_robots (courts.ns.ca robots.txt: Drupal system paths only; Courts of Nova Scotia official consolidated rules PDF)", "Nova Scotia court rules; Crown copyright, reproduction of the rules permitted by the Courts of Nova Scotia", ["ca-ns-superior-court", "ca-ns-court-of-appeal"], "rule set applies to this court (Supreme Court and Court of Appeal of Nova Scotia)")
def ca_pe():
    t = open(f"{CRAW}/pe_rcp.txt", errors="ignore").read(); sh = sha(f"{CRAW}/pe_rcp.pdf")
    rx = re.compile(r"^(\d{1,2}\.\d{2}(?:\.\d)?)(?:[ \t]+|(?=\())(?=\(|[A-Z])(?![A-Z0-9 ,;&'’()-]+$)(\S.*)$")
    r = _split_lines(t, rx, titlefn=lambda L, i, m: None)
    r = [(f"Rule {k}", ti, b) for k, ti, b in r]
    return _ca("ca-pe-rcp", "Prince Edward Island Rules of Civil Procedure (consolidation 2025)", "ca", "CA-PE", r, "https://www.courts.pe.ca/sites/test.courts.pe.ca/files/WordRules2023-REV_2025_1.pdf", sh, "allowed_by_robots (courts.pe.ca robots.txt: Drupal system paths only; Courts of PEI complete rules PDF)", "Prince Edward Island court rules; Crown copyright, reproduction of the rules permitted by the Courts of PEI", ["ca-pe-superior-court", "ca-pe-court-of-appeal"], "rule set applies to this court (Supreme Court and Court of Appeal of Prince Edward Island)")
def ca_sk():
    t = open(f"{CRAW}/sk_kbr.txt", errors="ignore").read(); sh = sha(f"{CRAW}/sk_kbr.pdf")
    t = t[t.find("PART 1: FOUNDATIONAL RULES", 3000):]
    rx = re.compile(r"^ {3,6}(\d{1,2}-\d{1,3})(?:[ \t]+|(?=\())(?=\S)")
    def ti(L, i, m):
        j = i - 1
        while j > 0 and not L[j].strip(): j -= 1
        c = L[j].strip(); return c if len(c) < 90 and not re.match(r"^\d{1,3}-\d{1,3}\b", c) else None
    r = _split_lines(t, rx, titlefn=ti)
    r = [(f"Rule {k}", t_, b) for k, t_, b in r]
    return _ca("ca-sk-kbr", "The King's Bench Rules (Saskatchewan), Parts 1 to 18", "ca", "CA-SK", r, "https://publications.saskatchewan.ca/api/v1/products/73108/formats/81637/download", sh, "no_robots_txt (publications.saskatchewan.ca robots.txt returns 404; Publications Saskatchewan public download of The King's Bench Rules)", "Saskatchewan legislation; Crown copyright, reproduction permitted by Publications Saskatchewan terms (non-commercial and commercial reuse of statutes)", ["ca-sk-superior-court", "ca-sk-court-of-appeal"] if False else ["ca-sk-superior-court"], "rule set applies to this court (Court of King's Bench for Saskatchewan)")
def ca_mb():
    from lxml import html as lh
    raw = open(f"{CRAW}/mb_kbr.html", "rb").read(); sh = sha(f"{CRAW}/mb_kbr.html"); d = lh.fromstring(raw); out = []
    acc = {}; order = []
    for div in d.xpath('//div[contains(@class,"regrow") and @id]'):
        i = div.get("id"); base = i.split("(")[0]
        if not re.fullmatch(r"\d+[A-Z]{0,2}(?:\.\d+[A-Z]?){0,2}", base): continue
        cols = div.xpath('.//div[contains(@class,"regcol-e")]')
        if not cols: continue
        c = cols[0]; h = c.xpath('.//*[contains(@class,"secheading")]'); title = ws2(h[0].text_content()) if h else None
        text = ws2(c.text_content())
        if title and text.startswith(title): text = text[len(title):].strip()
        if base not in acc: acc[base] = [title, []]; order.append(base)
        elif title and not acc[base][0]: acc[base][0] = title
        acc[base][1].append(text)
    o2 = []
    for b in order:
        t_, parts = acc[b]; txt_ = ws2(" ".join(parts))
        if len(txt_) > 10 and re.search(r"\d", b) and "." in b: o2.append((f"Rule {b}", t_, txt_[:12000]))
    return _ca("ca-mb-kbr", "Court of King's Bench Rules, M.R. 553/88 (Manitoba)", "ca", "CA-MB", o2, "https://web2.gov.mb.ca/laws/regs/current/553-88.php", sh, "robots_unknown:no_robots_txt (web2.gov.mb.ca/robots.txt returns a 404 page; Manitoba Laws official HTML)", "Manitoba regulation; Crown copyright, reproduction permitted under the Manitoba Laws website terms", ["ca-mb-superior-court"], "rule set applies to this court (Court of King's Bench of Manitoba)")
B.update(CA_NS=ca_ns, CA_PE=ca_pe, CA_SK=ca_sk, CA_MB=ca_mb)

def ca_nl():
    import glob
    out = []; seen = set(); h = hashlib.sha256()
    for f in sorted(glob.glob(f"{CRAW}/nl/*.htm"), key=lambda x: x.lower()):
        raw = open(f, "rb").read(); h.update(raw); s = raw.decode("utf-8", "ignore")
        t = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S); t = re.sub(r"<[^>]+>", "\n", t)
        import html as _h
        L = [ws2(_h.unescape(x)) for x in t.split("\n")]; L = [x for x in L if x]
        idx = [i for i, x in enumerate(L) if re.fullmatch(r"\d{1,2}[A-Z]?\.\d{2}[A-Z]?(?:\.\d)?\.", x)]
        for j, i in enumerate(idx):
            k = L[i][:-1]; e = (idx[j + 1] - 1) if j + 1 < len(idx) else len(L)
            body = ws2(" ".join(L[i + 1:e])); title = L[i - 1] if i > 0 and len(L[i - 1]) < 120 else None
            body = re.sub(r"\s*1986 c42.*$", "", body)
            if k in seen or len(body) < 10: continue
            seen.add(k); out.append((f"Rule {k}", title, body[:12000]))
    return _ca("ca-nl-rsc", "Rules of the Supreme Court, 1986 (Newfoundland and Labrador), Newfoundland Regulation 52/97", "ca", "CA-NL", out, "https://www.assembly.nl.ca/legislation/sr/regulations/rc86rules.htm", h.hexdigest(), "allowed_by_robots (assembly.nl.ca robots.txt disallows only /search; House of Assembly official version, per-Rule HTML pages)", "Newfoundland and Labrador regulation; Crown copyright, reproduction permitted by the Queen's Printer under the Statutes terms", ["ca-nl-superior-court", "ca-nl-court-of-appeal"], "rule set applies to this court (Supreme Court of Newfoundland and Labrador; Court of Appeal has its own rules)")
B.update(CA_NL=ca_nl)

def ca_fcr():
    from lxml import etree
    b = open(f"{CRAW}/fcr.xml", "rb").read(); sh = hashlib.sha256(b).hexdigest(); r = etree.fromstring(b); out = []; head = None; seen = set()
    body = r.find("Body"); LIMS = "{http://justice.gc.ca/lims}inforce-start-date"
    for e in body.iter():
        if e.tag == "Heading":
            t = e.find("TitleText"); head = ws2("".join(t.itertext())) if t is not None else head
        elif e.tag == "Section":
            lab = e.find("Label")
            if lab is None or not (lab.text or "").strip(): continue
            k = lab.text.strip(); mn = e.find("MarginalNote"); t = ws2(" ".join(e.itertext())); mt = ws2("".join(mn.itertext())) if mn is not None else ""; t = re.sub(r"^" + re.escape(mt) + r"\s*" + re.escape(k) + r"\s*", "", t) if mt else re.sub(r"^" + re.escape(k) + r"\s*", "", t)
            if k in seen or len(t) < 10: continue
            seen.add(k); out.append((f"Rule {k}", ws2("".join(mn.itertext())) if mn is not None else head, t[:12000]))
    return _ca("ca-fcr", "Federal Courts Rules (SOR/98-106), consolidation of 21 December 2025", "ca", "CA", out, "https://laws-lois.justice.gc.ca/eng/regulations/SOR-98-106/index.html", sh, "archive_wayback (Justice Laws XML SOR-98-106 snapshot 2026-09-21; the live site is not reachable from the box; laws-lois.justice.gc.ca robots.txt has crawl-delay 10 and disallows /assets/ only)", "Reproduction of federal law (Justice Laws Website reproduction terms; Government of Canada)", ["ca-fc", "ca-fca"], "rule set applies to this court (Federal Court and Federal Court of Appeal)")
B.update(CA_FCR=ca_fcr)

def merge(cc, key, rows, xw):
    d = f"{ROOT}/data/{cc}"; sid = rows[0]["rule_set_id"]
    p = f"{d}/{cc}_rules.jsonl"; old = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    old = [r for r in old if r["rule_set_id"] != sid]; wjl(p, old + dedupe(rows))
    px = f"{d}/{cc}_rules_crosswalk.jsonl"; ox = [json.loads(l) for l in open(px)] if os.path.exists(px) else []
    ox = [r for r in ox if r["rule_set_id"] != sid]; wjl(px, ox + xw); print(key, "rules written", len(rows), flush=True)
if __name__ == "__main__":
    for k in sys.argv[1:]:
        rows, xw = B[k](); merge(k.split("_")[0].lower(), k, rows, xw)
