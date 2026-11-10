"""Top-court judge rosters for rest-of-world countries (official roster pages only; name/title/role; needs_review=true).
Usage: row_judges.py CC.. -> data/<cc>/<cc>_judges.jsonl"""
import sys, gzip, datetime
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW, cached
from bs4 import BeautifulSoup
def dec(b): return gzip.decompress(b) if b and b[:2] == b"\x1f\x8b" else b
def J(cc, court, name, title, ptype, url, roster, pol, ext, lic, term_start=None, status="sitting", **kw):
    return dict(judge_id=f"{cc.lower()}-{court}-{slug(name) or __import__('hashlib').sha1(name.encode()).hexdigest()[:10]}", court_id=f"{cc.lower()}-{court}", name=name, title=title, position_type=ptype, term_start=term_start, term_end=None, status=status, roster_url=roster,
                source_url=url, site_policy=pol, retrieved_at=NOW(), needs_review=True, extraction=ext, license=lic, **kw)
def lines(b):
    s = BeautifulSoup(dec(b), "html.parser"); m = s.find("main") or s
    for t in m(["script", "style", "nav", "footer"]): t.decompose()
    return [l.strip() for l in m.get_text("\n", strip=True).split("\n") if l.strip()]
def nz():
    out = []; lic = "CC-BY-4.0 (Courts of New Zealand)"
    pre = re.compile(r"^(?:Acting Judge\s+)?The (?:Right )?Honourable (?:Justice |Dame |Sir |Mr Justice |Ms Justice )?")
    def clean(n): return re.sub(r"\s+(GNZM|KNZM|DNZM|CNZM|ONZM|MNZM|QSO|KC)\b", "", pre.sub("", n)).strip()
    # Supreme Court (live page answers the box with a human-verification page -> Wayback snapshot 2025-12-29)
    b, u, pol = cached("https://web.archive.org/web/20251229152303id_/https://www.courtsofnz.govt.nz/the-courts/supreme-court/judges", "intl_nz_sc_judges.html", delay=3)
    L = lines(b); i0 = L.index("Judges of the Supreme Court") if "Judges of the Supreme Court" in L else 0; acting = False
    for l in L[i0:]:
        if l.startswith("Acting Judges"): acting = True; continue
        if l.startswith("Practice in relation"): break
        if re.match(r"^The (Right )?Honourable", l) and "," not in l.replace(", Chief Justice", "") or "Chief Justice of New Zealand" in l and l.startswith("The Right"):
            chief = "Chief Justice" in l; nm = clean(l.split(",")[0])
            out.append(J("NZ", "supreme-court", nm, "Chief Justice of New Zealand" if chief else ("Acting Judge of the Supreme Court" if acting else "Judge of the Supreme Court"), "chief" if chief else ("acting" if acting else "associate"),
                         "https://www.courtsofnz.govt.nz/the-courts/supreme-court/judges", "https://www.courtsofnz.govt.nz/the-courts/supreme-court/judges", pol + "|archive_wayback(live_captcha_not_bypassed;snapshot=2025-12-29)", "roster_list(honorific lines)", lic, status="acting" if acting else "sitting"))
    seen = set(); out = [x for x in out if not (x["judge_id"] in seen or seen.add(x["judge_id"]))]
    # Court of Appeal (live)
    b, u, pol = cached("https://www.courtsofnz.govt.nz/the-courts/court-of-appeal/judges", "intl_nz_coa_judges.html", delay=3)
    L = lines(b); pres = False; n0 = len(out)
    for k, l in enumerate(L):
        if l.startswith("President of the Court of Appeal"): pres = True; continue
        m = re.match(r"^(Acting Judge )?The (Right )?Honourable (Justice|Dame|Sir)", l)
        if m and len(l) < 80:
            nm = clean(l); ptype = "chief" if pres else ("acting" if m.group(1) else "associate"); pres = False
            out.append(J("NZ", "court-of-appeal", nm, "President of the Court of Appeal" if ptype == "chief" else "Judge of the Court of Appeal" + (" (acting)" if m.group(1) else ""), ptype,
                         "https://www.courtsofnz.govt.nz/the-courts/court-of-appeal/judges", "https://www.courtsofnz.govt.nz/the-courts/court-of-appeal/judges", pol, "roster_list(honorific lines)", lic, status="acting" if m.group(1) else "sitting"))
    print("NZ judges SC", n0, "CoA", len(out) - n0)
    return out
def _d(x):
    try: return datetime.datetime.strptime(x, "%d-%m-%Y").date().isoformat()
    except Exception: return None
def india():
    out = []; lic = "Supreme Court of India public website (sci.gov.in); official roster, reuse per site terms"
    b, u, pol = cached("https://www.sci.gov.in/chief-justice-judges/", "intl_in_sci_judges.html", delay=3)
    s = BeautifulSoup(dec(b), "html.parser")
    for t in s(["script", "style", "nav", "footer", "header"]): t.decompose()
    L = [l for l in (s.find("main") or s).get_text("\n", strip=True).split("\n")]
    for i, l in enumerate(L):
        if l.startswith("Justice ") and i > 0 and L[i - 1] == "Hon'ble":
            nm = re.sub(r"^Justice\s+", "", l).strip(); seg = L[i + 1:i + 14]; cji = (i < 15)
            txt = " ".join(seg); m1 = re.search(r"\(DoA\)\s*(\d\d-\d\d-\d{4})", txt); m2 = re.search(r"\(DoR\)\s*(\d\d-\d\d-\d{4})", txt)
            doa = _d(m1.group(1)) if m1 else None; dor = _d(m2.group(1)) if m2 else None
            j = J("IN", "supreme-court", nm, "Chief Justice of India" if cji else "Judge of the Supreme Court of India", "chief" if cji else "associate", "https://www.sci.gov.in/chief-justice-judges/", "https://www.sci.gov.in/chief-justice-judges/", pol, "roster_page(Hon'ble/Justice/DoA/DoR lines)", lic, term_start=doa)
            j["term_end"] = dor; out.append(j)
    print("IN judges SC", len(out)); return out
def japan():
    lic = "Supreme Court of Japan (courts.go.jp) published roster; reuse per site terms"; out = []
    b, u, pol = cached("https://www.courts.go.jp/saikosai/about/saibankan/index.html", "intl_jp_sc_judges.html", delay=3)
    L = lines(b); i0 = L.index("最高裁判所長官") if "最高裁判所長官" in L else 0; role = None; i = i0
    seg = L[i0:]; k = 0
    while k < len(seg):
        x = seg[k]
        if x in ("最高裁判所長官", "最高裁判所判事"): role = x; k += 1; continue
        if x.startswith("最高裁判所判事一覧"): break
        if role and k + 1 < len(seg) and re.match(r"第[一二三]小法廷", seg[k + 1]):
            nm = re.sub(r"\s+", " ", x); chief = role == "最高裁判所長官"
            j = J("JP", "supreme-court", nm, "Chief Justice of the Supreme Court" if chief else "Justice of the Supreme Court", "chief" if chief else "associate", "https://www.courts.go.jp/saikosai/about/saibankan/index.html",
                  "https://www.courts.go.jp/saikosai/about/saibankan/index.html", pol, "roster_page(role heading, name, petty bench)", lic, name_local=nm, title_local=role, petty_bench=seg[k + 1])
            out.append(j); k += 2; continue
        k += 1
    print("JP judges SC", len(out)); return out
def za():
    snap = "https://web.archive.org/web/20261015091214/https://www.concourt.org.za/index.php/judges/current-judges"; live = "https://www.concourt.org.za/index.php/judges/current-judges"
    b, u, pol = cached("https://web.archive.org/web/20261015091214id_/https://www.concourt.org.za/index.php/judges/current-judges", "za_cc_judges.html", delay=3)
    h = BeautifulSoup(dec(b), "html.parser"); out = []; full = {"Dambuza": "Nambitha Christabel Dambuza-Mayosi", "Savage": "Katharine Mary Savage"}
    for a in h.find_all("a", href=re.compile(r"/judges/current-judges/\d+-")):
        t = re.sub(r"\s+", " ", a.get_text(" ", strip=True).replace("\xa0", " ")).strip(); m = re.match(r"^(Chief Justice|Deputy Chief Justice|Justice)\s+(.+)$", t)
        if not m: continue
        role, nm = m.groups(); nm = full.get(nm, nm); chief = role == "Chief Justice"
        ttl = {"Chief Justice": "Chief Justice of South Africa", "Deputy Chief Justice": "Deputy Chief Justice of South Africa", "Justice": "Justice of the Constitutional Court"}[role]
        r = J("ZA", "constitutional-court", nm, ttl, "chief" if chief else ("deputy_chief" if role.startswith("Deputy") else "associate"), "https://www.concourt.org.za" + a["href"], live, pol + "|archive_wayback(live_host_tls_unreachable_from_box;snapshot=2026-10-15)", "official roster page, Wayback snapshot 2026-10-15; full names of Dambuza-Mayosi and Savage from Presidency media statement 2026-04-10", "Constitutional Court of South Africa public website; reuse per site terms")
        out.append(r)
    seen = set(); return [x for x in out if not (x["judge_id"] in seen or seen.add(x["judge_id"]))]
def br():
    b, u, pol = cached("https://portal.stf.jus.br/ostf/", "br_stf_ostf.html", delay=3)
    t = BeautifulSoup(dec(b), "html.parser"); txt = [l.strip() for l in t.get_text("\n", strip=True).split("\n") if l.strip()]; out = []
    i0 = txt.index("Composição do Plenário do STF") if "Composição do Plenário do STF" in txt else 0
    k = i0
    while k < len(txt) - 2:
        if txt[k] in ("Ministro", "Ministra"):
            nm = txt[k + 1]; pres = txt[k + 2] == "Presidente"; d = txt[k + 3 if pres else k + 2]; m = re.match(r"^\((\d\d)/(\d\d)/(\d{4})\)$", d)
            out.append(J("BR", "national-supreme-stf", nm, "Presidente do Supremo Tribunal Federal" if pres else "Ministra do Supremo Tribunal Federal" if txt[k] == "Ministra" else "Ministro do Supremo Tribunal Federal", "chief" if pres else "associate",
                         "https://portal.stf.jus.br/ostf/", "https://portal.stf.jus.br/ostf/", pol, "official roster page 'Composição do Plenário do STF'; seat vacant since Oct 2025 (Barroso retirement), 10 of 11 ministers", "Supremo Tribunal Federal public website; reuse per site terms",
                         term_start=f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None)); k += 3
        else: k += 1
        if txt[k:k + 1] and txt[k].startswith("1ª TURMA"): break
    seen = set(); return [x for x in out if not (x["judge_id"] in seen or seen.add(x["judge_id"]))]
def mx():
    b, u, pol = cached("https://www.scjn.gob.mx/conoce-la-corte", "mx_scjn_conoce.html", delay=3)
    h = BeautifulSoup(dec(b), "html.parser"); out = []; first = True
    for a in h.find_all("a", href=re.compile(r"^/ministr[oa]-")):
        nm = re.sub(r"\s+", " ", a.get_text(" ", strip=True)); nm = re.sub(r"^.*\bMinistr[oa]\s+", "", nm).strip()
        if not nm: continue
        fem = a["href"].startswith("/ministra"); pres = first; first = False
        out.append(J("MX", "scjn", nm, "Presidente de la Suprema Corte de Justicia de la Nación" if pres else ("Ministra de la SCJN" if fem else "Ministro de la SCJN"), "chief" if pres else "associate", "https://www.scjn.gob.mx" + a["href"], "https://www.scjn.gob.mx/conoce-la-corte", pol,
                     "official 'Conoce la Corte' page: Pleno of nine ministers (2025 judicial reform)", "Suprema Corte de Justicia de la Nación public website; reuse per site terms"))
    seen = set(); return [x for x in out if not (x["judge_id"] in seen or seen.add(x["judge_id"]))]
BUILD = {"NZ": nz, "IN": india, "JP": japan, "ZA": za, "BR": br, "MX": mx}
if __name__ == "__main__":
    for cc in sys.argv[1:]:
        rows = BUILD[cc](); os.makedirs(f"{ROOT}/data/{cc.lower()}", exist_ok=True); wjl(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_judges.jsonl", rows); print(cc, len(rows))
