"""Depth-pass-6 rules for 8 countries lacking them (Europe, Middle East, Africa), all from official publishers or Wayback copies of them.
CH (Fedlex filestore HTML: ZPO SR 272, StPO SR 312.0, BGG SR 173.110), IS (Althingi lagasafn 91/1991 and 88/2008 via Wayback; live site is Cloudflare-challenged),
LU (Legilux NCPC consolidated 19 Dec 2025), LI (Lilex ZPO), AE (UAE Legislation portal Federal Decree-Law 42/2022 PDF via Wayback; live download is Cloudflare-challenged),
ZM (Ministry of Legal Affairs Laws of Zambia, High Court Act Cap 27 incl. High Court Rules), BW (Administration of Justice: Rules of the High Court 2011, SI 1/2011),
SC (Judiciary of Seychelles: Seychelles Code of Civil Procedure Cap 213).
usage: row_rules9.py KEY.. (keys CH IS LU LI AE ZM BW SC)"""
import sys, re, html, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_rules8 import *
from row_rules8 import _split_lines
R6 = f"{RAW}"
def txt(h): return ws2(html.unescape(re.sub(r"<[^>]+>", " ", h)))
def S(p): return sha(p)
def build(cc, sid, name, items, url, sh, pol, lic, lang, courts, basis, eff=None):
    rows = [rr(sid, cc.upper(), name, cc.upper(), n, t, b[:12000], url, sh, pol, lic, lang, eff) for n, t, b in items if b and len(b) >= 10]
    print(sid, len(rows)); return rows, xwalk(cc.upper(), sid, name, courts, url, basis)
FED_POL = "robots_ok (fedlex.admin.ch robots allow /; file located via the public Fedlex SPARQL endpoint)"; FED_LIC = "Swiss federal law; official publication, free reuse (Art. 5 URG: laws are not protected)"
def fedlex(p):
    s = open(p, encoding="utf-8").read(); out = []
    for m in re.finditer(r'<article id="art_([^"]+)">(.*?)</article>', s, re.S):
        h = re.search(r'<h6[^>]*>(.*?)</h6>', m.group(2), re.S); head = txt(h.group(1)) if h else ""
        mm = re.match(r"(Art\.\s*\S+)\s*(.*)", head); num = mm.group(1) if mm else "Art. " + m.group(1); title = (mm.group(2) if mm else head) or None
        body = txt(m.group(2)[h.end():] if h else m.group(2))
        if "Aufgehoben" in body[:40] and len(body) < 120: continue
        out.append((num, title, body))
    return out
def ch():
    rows, xw = [], []
    for f, sid, name, url, courts in [("zpo.html", "ch-zpo", "Schweizerische Zivilprozessordnung (ZPO, SR 272), Stand 1. Juli 2026", "https://www.fedlex.admin.ch/eli/cc/2010/262/de", ["ch-high-court", "ch-lower-court", "ch-court-of-appeal"]),
            ("2010_267.html", "ch-stpo", "Schweizerische Strafprozessordnung (StPO, SR 312.0), Stand 1. April 2025", "https://www.fedlex.admin.ch/eli/cc/2010/267/de", ["ch-high-court", "ch-lower-court", "ch-court-of-appeal"]),
            ("2006_218.html", "ch-bgg", "Bundesgesetz über das Bundesgericht (BGG, SR 173.110), Stand 1. April 2026", "https://www.fedlex.admin.ch/eli/cc/2006/218/de", ["ch-supreme-court"])]:
        p = f"{R6}/ch/{f}"; r, x = build("ch", sid, name, fedlex(p), url, S(p), FED_POL, FED_LIC, "de", courts, "rule set applies to this court"); rows += r; xw += x
    return rows, xw
def is_():
    rows, xw = [], []
    for f, sid, name, courts in [("1991091", "is-eml", "Lög um meðferð einkamála nr. 91/1991", ["is-lower-court", "is-court-of-appeal", "is-supreme-court"]), ("2008088", "is-msl", "Lög um meðferð sakamála nr. 88/2008", ["is-lower-court", "is-court-of-appeal", "is-supreme-court"])]:
        p = f"{R6}/is/{f}.html"; s = open(p, encoding="utf-8").read(); parts = re.split(r'<b>\[?(\d+\. gr\.(?: [a-z]\.)?)\]?</b>', s); out = []; seen = set()
        for i in range(1, len(parts) - 1, 2):
            k = parts[i]; b = txt(re.split(r'<span id="G\d+[A-Z]*"></span>', parts[i + 1])[0])
            if k in seen: continue
            seen.add(k); out.append((k, None, b))
        r, x = build("is", sid, name, out, f"https://www.althingi.is/lagas/nuna/{f}.html", S(p), "archive_wayback (Althingi lagasafn page, 2026 Wayback snapshot; live althingi.is returns a Cloudflare challenge, not bypassed; robots allows /lagas/)", "Icelandic statute (Althingi lagasafn); official text, laws not subject to copyright (Copyright Act art. 9)", "is", courts, "rule set applies to this court"); rows += r; xw += x
    return rows, xw
def lu():
    p = f"{R6}/lu/ncpc.html"; s = open(p, encoding="utf-8").read(); out = []; seen = set()
    for m in re.finditer(r'<div id="(art_[^"]+)" class="richtext_article">(.*?)(?=<div id="art_|<div class="richtext_heading|\Z)', s, re.S):
        n = re.search(r'richtext_num_article[^>]*>(.*?)</p>', m.group(2), re.S); num = txt(n.group(1)).rstrip(".") if n else m.group(1)
        if num in seen: continue
        b = txt(m.group(2)[n.end():] if n else m.group(2)); seen.add(num); out.append((num, None, b))
    return build("lu", "lu-ncpc", "Nouveau Code de procédure civile (version consolidée Legilux du 19 décembre 2025)", out, "https://legilux.public.lu/eli/etat/leg/code/procedure_civile/20251219", S(p), "robots_ok (data.legilux.public.lu; /eli/etat/leg/code not disallowed)", "Luxembourg legislation, Legilux consolidated text (documentary value only); official texts free of copyright", "fr", ["lu-ordinary-limited", "lu-ordinary-general", "lu-ordinary-appellate", "lu-ordinary-supreme"], "rule set applies to this court")
def li():
    p = f"{R6}/li/zpo.html"; s = html.unescape(open(p, encoding="utf-8").read()); t = re.sub(r"<[^>]+>", "\n", s); t = re.sub(r"\n\s*\n+", "\n", t)
    out = []; seen = set(); last = 0
    for k, t2, b in _split_lines(t, re.compile(r"^\s*§\s*(\d+[a-z]?)\s*$")):
        n = int(re.match(r"\d+", k).group())
        if n < last: continue
        last = n; out.append((f"§ {k}", None, b))
    return build("li", "li-zpo", "Zivilprozessordnung (ZPO, LGBl. 1912 Nr. 9/1, LR 271.0), konsolidierte Fassung Lilex", out, "https://www.gesetze.li/konso/1912009001", S(p), "robots_ok (gesetze.li has no robots.txt)", "Liechtenstein law, official Lilex consolidation; official texts free of copyright", "de", ["li-lower-court", "li-court-of-appeal", "li-supreme-court"], "rule set applies to this court")
def ae():
    p = f"{R6}/ae/cpc.txt"; L = open(p).read().split("\n"); st = [i for i, l in enumerate(L) if re.match(r"^\s*Article\s*\(1\)", l)][1]
    t = "\n".join(L[st:]); out = []; last = 0
    for k, _, b in _split_lines(t, re.compile(r"^\s*Article\s*\((\d+)\)\s*(.*)$")):
        n = int(k)
        if n < last: continue
        last = n; out.append((f"Article {k}", None, b))
    return build("ae", "ae-cpc-2022", "Civil Procedure Code (Federal Decree-Law No. 42 of 2022), official English translation", out, "https://uaelegislation.gov.ae/en/legislations/1602", sha(f"{R6}/ae/cpc.pdf"), "archive_wayback (UAE Legislation portal PDF, 2026 Wayback snapshot; live download is Cloudflare-challenged, not bypassed; robots allows all)", "UAE federal legislation, official portal translation (Arabic text prevails)", "en", ["ae-federal-supreme-court", "ae-court-of-cassation", "ae-court-of-appeal", "ae-court-of-first-instance"], "rule set applies to this court", "2023-01-02")
ROM = {c: v for c, v in zip("IVXLC", [1, 5, 10, 50, 100])}
def rom(s):
    v = 0
    for i, c in enumerate(s): v += -ROM[c] if i + 1 < len(s) and ROM[c] < ROM[s[i + 1]] else ROM[c]
    return v
def orders(t, rx, conv):
    out = []; last = 0
    for k, _, b in _split_lines(t, rx, drop=lambda l: "Copyright Ministry of Legal Affairs" in l or l.strip() == "The Laws of Zambia"):
        n = conv(k)
        if n <= last: continue
        last = n; out.append((f"Order {k}", None, b))
    return out
def zm():
    p = f"{R6}/zm/hcr.txt"; L = open(p).read().split("\n"); st = max(0, [i for i, l in enumerate(L) if "These Rules may be cited as the High Court Rules" in l][0] - 8)
    out = orders("\n".join(L[st:]), re.compile(r"^\s+ORDER ([IVXLC]+)\s*$"), rom)
    return build("zm", "zm-hcr", "High Court Rules (Laws of Zambia, Cap 27 subsidiary legislation)", out, "https://www.parliament.gov.zm/sites/default/files/documents/acts/High%20Court%20Act.pdf", sha(f"{R6}/zm/hcr.pdf"), "archive_wayback (National Assembly of Zambia PDF of Cap 27, Wayback 2026 snapshot)", "Laws of Zambia (Ministry of Legal Affairs edition); official text", "en", ["zm-high-court"], "rule set applies to this court")
def bw():
    p = f"{R6}/bw/hcr.txt"; L = open(p).read().split("\n"); st = [i for i, l in enumerate(L) if re.match(r"^\s+ORDER 1\s*$", l)][0] - 1
    out = orders("\n".join(L[st:]), re.compile(r"^\s+ORDER (\d+)\s*$"), int)
    return build("bw", "bw-hcr-2011", "Rules of the High Court, 2011 (SI No. 1 of 2011)", out, "https://www.justice.gov.bw/sites/default/files/SI_1_12_01_11_High%20Court.pdf", sha(f"{R6}/bw/hcr.pdf"), "robots_ok (justice.gov.bw crawl-delay 10 respected; /sites/default/files not disallowed)", "Botswana Government Gazette statutory instrument; official text", "en", ["bw-high-court"], "rule set applies to this court", "2011-01-12")
def sc():
    p = f"{R6}/sc/cpc.txt"; L = open(p).read().split("\n"); st = [i for i, l in enumerate(L) if re.match(r"^\s+1\. Short title\s*$", l)][0]
    out = []; last = 0
    for k, t2, b in _split_lines("\n".join(L[st:]), re.compile(r"^\s{0,4}(\d+[A-Z]?)\.\s+([A-Z][^.]{2,100})$"), drop=lambda l: "......" in l):
        n = int(re.match(r"\d+", k).group())
        if n < last or n > last + 40: continue
        last = n; out.append((f"Section {k}", t2, b))
    return build("sc", "sc-cpc", "Seychelles Code of Civil Procedure (Cap 213), consolidated to 1 December 2014", out, "https://www.judiciary.sc/wp-content/uploads/2026/08/seychelles-code-of-civil-procedure-1855-cap-213.pdf", sha(f"{R6}/sc/cpc.pdf"), "robots_ok (judiciary.sc disallows /wp-admin/ only)", "Laws of Seychelles, Judiciary of Seychelles publication; official text", "en", ["sc-supreme-court", "sc-lower-court"], "rule set applies to this court")
B.update(CH=ch, IS=is_, LU=lu, LI=li, AE=ae, ZM=zm, BW=bw, SC=sc)
if __name__ == "__main__" and "row_rules9" in sys.argv[0]:
    for k in sys.argv[1:]:
        rows, xw = B[k]()
        for sid in dict.fromkeys(r["rule_set_id"] for r in rows):  # merge each rule set separately so re-runs replace, not duplicate
            merge(k.lower(), k, [r for r in rows if r["rule_set_id"] == sid], [x for x in xw if x["rule_set_id"] == sid])
