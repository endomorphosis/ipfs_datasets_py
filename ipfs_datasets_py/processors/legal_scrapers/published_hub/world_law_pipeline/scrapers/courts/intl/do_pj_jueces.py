"""DO: Poder Judicial 'Listado General de Jueces' (transparencia.poderjudicial.gob.do/consultasSCJ/consultaJueces, ASP.NET grid
embedded in poderjudicial.gob.do/sobre-nosotros/carrera-judicial/listado-general-de-jueces/; that iframe URL was found via the
Common Crawl CC-MAIN-2025-47 capture since poderjudicial.gob.do returns 403 to the box). Robots: transparencia host allows all
except /reportePDF/. Name-search on each vowel, paginate, union. Public name + post + tribunal only (internal ids not stored)."""
import json, re, html, time, datetime, hashlib, os, sys, requests, unicodedata
ROOT = "/workspace/world_courts"; OUT = f"{ROOT}/data/do/do_judges.jsonl"
U = "https://transparencia.poderjudicial.gob.do/consultasSCJ/consultaJueces"
ROSTER = "https://poderjudicial.gob.do/sobre-nosotros/carrera-judicial/listado-general-de-jueces/"
P = "ctl00$ContentPlaceHolder1$ucConsultaJueces$"; now = datetime.datetime.now(datetime.UTC).isoformat()
POL = "robots_allowed|transparencia.poderjudicial.gob.do (Poder Judicial RD): 'Términos de Uso', © Todos los Derechos Reservados; no open licence stated"
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (world_courts research; public court data)"
def hidden(t): return {m.group(1): html.unescape(m.group(2)) for m in re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', t)}
def rows(t):
    i = t.find('dtgDetalle"'); out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", t[i:], re.S):
        td = [re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", x))).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(td) >= 4 and td[0].isdigit() and not td[1].isdigit() and len(td[0]) >= 6: out.append(tuple(td[:4]))
    return out
def post(f):
    for k in range(6):
        try:
            r = s.post(U, data=f, timeout=120); time.sleep(3)
            if r.status_code == 200 and "noencontrada" not in r.text: return r.text
            print("post status", r.status_code, len(r.text), flush=True); time.sleep(15 * (k + 1))
        except requests.RequestException as e: print("err", str(e)[:100], flush=True); time.sleep(15 * (k + 1))
    return ""
allr = {}
CACHED = [r for f in os.environ.get("DO_ROWS_JSON", "").split(",") if f for r in json.load(open(f))]  # rows saved by an earlier paginated pass
for r in CACHED: allr.setdefault(r[0], tuple(r))
for q in ("" if CACHED else (sys.argv[1] if len(sys.argv) > 1 else "aeiou")):
    t = s.get(U, timeout=60).text; time.sleep(3)
    f = hidden(t) | {P + "txtNombre": q, P + "ddlDepartamento": "0", P + "btnSend": "Buscar"}
    t = post(f); pg = 1; seen_pages = set(); retry_f = None
    while t:
        rr = rows(t); key = tuple(rr)
        if (not rr or key in seen_pages) and retry_f is not None:
            print("retry page", pg, flush=True); time.sleep(10); t = post(retry_f); retry_f = None; continue
        if not rr or key in seen_pages: break
        seen_pages.add(key)
        for r in rr: allr.setdefault(r[0], r)
        pg += 1
        if f"Page${pg}" not in t: break
        f = hidden(t) | {"__EVENTTARGET": P + "dtgDetalle", "__EVENTARGUMENT": f"Page${pg}", P + "txtNombre": q, P + "ddlDepartamento": "0"}
        t = post(f); retry_f = f
    print(q, "pages", pg, "total", len(allr), flush=True)
def slug(x): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()).strip("-")
def court(trib):
    T = trib.upper()
    if "S.C.J" in T or "SUPREMA" in T: return "do-supreme-court"
    if "CORTE" in T or "SUPERIOR" in T: return "do-court-of-appeal"
    if "PAZ" in T: return "do-lower-court"
    return "do-high-court"
def ptype(p):
    P_ = p.upper()
    if "PRESIDENTE S.C.J" in P_: return "chief"
    if "PRESIDENTE" in P_ or "PTE" in P_: return "presiding"
    return "associate"
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
oldn = {slug(r["name"]) for r in old}; oldids = {r["judge_id"] for r in old}
def ttl(x):
    t = x.strip().title()
    t = re.sub(r"(\d)(Ro|Do|Ra|Er|Er\.|Mo|To|Vo|No)\b", lambda m: m.group(1) + m.group(2).lower(), t)
    return re.sub(r"\b(De|Del|La|Las|Los|Y|E|En|Para)\b", lambda m: m.group(1).lower(), t).replace("S.C.j.", "S.C.J.")
def nm(x): return " ".join(w if w.endswith(".") and len(w) <= 5 and not w.isupper() else w.capitalize() for w in x.split()).replace(" Del ", " del ").replace(" De ", " de ").replace(" La ", " la ")
new = []
for mid, name, pst, trib in sorted(allr.values(), key=lambda r: r[1]):
    n = nm(name); sl = slug(n); jid = f"do-pj-{sl}"
    if sl in oldn: continue
    if court(trib) == "do-supreme-court" and any(o["court_id"] == "do-supreme-court" and slug(o["name"]).split("-")[-1] == sl.split("-")[-1] and slug(o["name"])[0] == sl[0] for o in old): continue
    k = 2
    while jid in oldids: jid = f"do-pj-{sl}-{k}"; k += 1
    oldids.add(jid)
    new.append({"judge_id": jid, "court_id": court(trib), "court_name_as_listed": trib, "name": n, "name_as_listed": name,
                "title": ttl(pst), "title_as_listed": pst, "position_type": ptype(pst), "term_start": None, "term_end": None, "status": "sitting",
                "jurisdiction": "DO", "roster_url": ROSTER, "source_url": U, "source_kind": "official", "site_policy": POL, "retrieved_at": now,
                "needs_review": False, "extraction": "Listado General de Jueces grid (Nombre, Puesto, Tribunal); name searched by vowel, paginated",
                "license": "official public information; no licence stated"})
with open(OUT, "a") as fo:
    for r in new: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
print("fetched", len(allr), "new", len(new))
