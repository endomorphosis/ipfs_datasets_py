"""Mexico procedural codes (one row per article, es): CNPCF (DOF 7-VI-2023), CNPP (DOF 5-III-2014), Ley de Amparo (DOF 2-IV-2013). diputados.gob.mx PDFs via Wayback (live host unreachable from the box). -> data/mx/mx_rules.jsonl + crosswalk"""
import sys, hashlib, subprocess
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
RAWD = f"{ROOT}/rules/raw/mx"
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def ws(s): return re.sub(r"\s+", " ", s or "").strip()
ART = re.compile(r"(?m)^[ \t]*Art[ií]culo[ \t]+(\d{1,4})[ \t]*[o°º]?(?:[ \t]*[\.\-]+)?[ \t]*((?:Bis|Ter|Qu[aá]ter|Quinquies|Sexies|Septies|Octies|Nonies|Decies)(?:[ \t]+[A-Z])?|[A-Z](?=[\.\- ]))?[ \t]*[\.\-–]")
SETS = [("mx-cnpcf-2023", "Código Nacional de Procedimientos Civiles y Familiares (DOF 07-06-2023)", "CNPCF", "2023-06-07", ["mx-scjn", "mx-tsj-" ]), ("mx-cnpp-2014", "Código Nacional de Procedimientos Penales (DOF 05-03-2014)", "CNPP", "2014-03-05", ["mx-scjn", "mx-tsj-"]),
        ("mx-amparo-2013", "Ley de Amparo, reglamentaria de los artículos 103 y 107 constitucionales (DOF 02-04-2013)", "LAmp", "2013-04-02", ["mx-scjn", "mx-tribunales-colegiados", "mx-juzgados-distrito"])]
def build(): 
    rows = []; xw = []
    for sid, name, f, eff, courts in SETS:
        p = f"{RAWD}/{f}.pdf"; t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.replace("\x0c", "\n"); url = f"https://www.diputados.gob.mx/LeyesBiblio/pdf/{f}.pdf"
        ms = list(ART.finditer(t)); seen = set(); n = 0
        for i, m in enumerate(ms):
            k = m.group(1) + (("-" + re.sub(r"\s+", "", m.group(2))) if m.group(2) else "")
            if k in seen: continue
            body = ws(t[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(t)]); body = re.split(r"\bTRANSITORIOS?\b", body)[0].strip()
            if len(body) < 12: continue
            seen.add(k); n += 1
            rows.append(dict(rule_id=f"{sid}:art{k}", rule_set_id=sid, court_id=None, jurisdiction="MX", rule_set=name, rule_number=f"Art. {k}", title=None, text=body[:12000], effective_date=eff, pdf_path=None, pdf_sha256=None, source_sha256=sha(p), source_url=url, site_policy="archive_wayback(live_diputados_unreachable)", retrieved_at=NOW(),
                             license="Cámara de Diputados (Mexico) official legislation; public domain (LFDA art. 14 I)", language="es"))
        print(sid, n, flush=True)
        ISO = "AGU BCN BCS CAM CHP CHH COA COL CMX DUR GUA GRO HID JAL MEX MIC MOR NAY NLE OAX PUE QUE ROO SLP SIN SON TAB TAM TLA VER YUC ZAC".split()
        for c in [y for c0 in courts for y in ([f"mx-tsj-{i.lower()}" for i in ISO] if c0.endswith("-") else [c0])]: xw.append(dict(rule_set_id=sid, rule_set=name, court_id=c, jurisdiction="MX", basis="national procedural code applying to this court tier", source_url=url, linked_rows="new"))
    os.makedirs(f"{ROOT}/data/mx", exist_ok=True); wjl(f"{ROOT}/data/mx/mx_rules.jsonl", rows); wjl(f"{ROOT}/data/mx/mx_rules_crosswalk.jsonl", xw); print("MX rules", len(rows))
if __name__ == "__main__": build()
