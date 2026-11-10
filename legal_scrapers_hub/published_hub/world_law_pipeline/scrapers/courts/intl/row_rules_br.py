"""Brazil procedural codes/rules, one row per article (pt): CPC (Lei 13.105/2015), CPP (Decreto-Lei 3.689/1941 compilado), Lei 9.099/1995 (Juizados Especiais), Regimento Interno do STF.
Statutes: planalto.gov.br via Wayback (live host unreachable from the box); RISTF: STF official normative-acts service PDF. -> data/br/br_rules.jsonl + crosswalk"""
import sys, hashlib, subprocess, gzip, html
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
RAWD = f"{ROOT}/rules/raw/br"
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def ws(s): return re.sub(r"\s+", " ", s or "").strip()
def html_text(p):
    b = open(p, "rb").read()
    if b[:2] == b"\x1f\x8b": b = gzip.decompress(b)
    t = b.decode("utf-8") if b.count(b"\xc3") > b.count(b"\xe7") else b.decode("latin-1")
    t = re.sub(r"(?s)<(script|style).*?</\1>", "", t); t = re.sub(r"(?i)</(p|div|tr|li|h\d)>|<br\s*/?>", "\n", t); return html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ").replace("\r", "")
ART = re.compile(r"(?m)^[ \t]*Art\.[ \t]*(\d{1,2}\.\d{3}|\d{1,4})(?:[ \t]*[º°o])?(?:[ \t]*-[ \t]*([A-Z]{1,2}))?[\.\-– ]")
def split(t):
    ms = list(ART.finditer(t)); out = {}; order = []
    for i, m in enumerate(ms):
        k = m.group(1).replace(".", "") + (m.group(2) or "")
        e = ms[i + 1].start() if i + 1 < len(ms) else len(t)
        if k not in out: out[k] = ws(t[m.end():e]); order.append(k)
    return [(k, out[k]) for k in order]
LIC_PL = "Presidency of Brazil (planalto.gov.br) official legislation; public domain (Lei 9.610/98 art. 8 IV)"
SETS = [
 ("br-cpc-2015", "Código de Processo Civil (Lei 13.105/2015)", "cpc.html", "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2015/lei/l13105.htm", "archive_wayback(live_planalto_unreachable)", ["br-national-supreme-stf", "br-national-supreme-stj", "br-national-supreme-tst", "br-national-supreme-tse", "br-national-supreme-stm"], "2015-03-16"),
 ("br-cpp-1941", "Código de Processo Penal (Decreto-Lei 3.689/1941, texto compilado)", "cpp.html", "https://www.planalto.gov.br/ccivil_03/decreto-lei/del3689compilado.htm", "archive_wayback(live_planalto_unreachable)", ["br-national-supreme-stf", "br-national-supreme-stj"], "1941-10-03"),
 ("br-jec-1995", "Lei dos Juizados Especiais Cíveis e Criminais (Lei 9.099/1995)", "jec.html", "https://www.planalto.gov.br/ccivil_03/leis/l9099.htm", "archive_wayback(live_planalto_unreachable)", [], "1995-09-26"),
]
def build():
    rows = []; xw = []
    for sid, name, fn, url, pol, courts, eff in SETS:
        p = f"{RAWD}/{fn}"; t = html_text(p); lst = split(t); sh = sha(p)
        for k, body in lst:
            if len(body) < 12: continue
            rows.append(dict(rule_id=f"{sid}:art{k}", rule_set_id=sid, court_id=None, jurisdiction="BR", rule_set=name, rule_number=f"Art. {k}", title=None, text=body[:12000], effective_date=eff, pdf_path=None, pdf_sha256=None, source_sha256=sh, source_url=url, site_policy=pol, retrieved_at=NOW(), license=LIC_PL, language="pt"))
        print(sid, len(lst), flush=True)
        for c in courts: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="BR", basis="national procedural code applying to this court tier", source_url=url, linked_rows="new"))
    # RISTF
    p = f"{RAWD}/ristf.pdf"; t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.replace("\x0c", "\n"); i0 = t.find("Disposição Inicial", t.find("Disposição Inicial") + 10)
    j = [x.start() for x in re.finditer(r"(?m)^[ \t]*Emenda Regimental\s+1,\s+de", t)]; i1 = [x for x in j if x > i0 + 100000][0] if [x for x in j if x > i0 + 100000] else len(t)
    lst = split(t[i0:i1]); sid = "br-ristf"; name = "Regimento Interno do Supremo Tribunal Federal (atualizado até a Emenda Regimental 59/2023)"; url = "https://api-atosnormativosprd.azurewebsites.net/api/normativo/apresentacao/consolidado/1737"; sh = sha(p)
    for k, body in lst:
        if len(body) < 12: continue
        rows.append(dict(rule_id=f"{sid}:art{k}", rule_set_id=sid, court_id=None, jurisdiction="BR", rule_set=name, rule_number=f"Art. {k}", title=None, text=body[:12000], effective_date="2023-12-18", pdf_path=None, pdf_sha256=None, source_sha256=sh, source_url=url, site_policy="robots_unknown:fetched_ok", retrieved_at=NOW(),
                     license="Supremo Tribunal Federal official publication (stf.jus.br normative acts service); reuse per site terms", language="pt"))
    print(sid, len(lst), flush=True); xw.append(dict(rule_set_id=sid, rule_set=name, court_id="br-national-supreme-stf", jurisdiction="BR", basis="internal rules of this court", source_url=url, linked_rows="new"))
    os.makedirs(f"{ROOT}/data/br", exist_ok=True); wjl(f"{ROOT}/data/br/br_rules.jsonl", rows); wjl(f"{ROOT}/data/br/br_rules_crosswalk.jsonl", xw); print("BR rules", len(rows))
if __name__ == "__main__": build()
