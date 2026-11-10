"""Chunk-2 courthouse + court_body builder: KR TW PH AR CO CL NG KE. Usage: row_courthouses2.py CC...  -> data/<cc>/<cc>_courthouses.jsonl
Sources: OSM amenity=courthouse (ODbL), Wikidata courthouses (CC0), compiled court-structure bodies (reference), GeoNames cities500 for nearest-city/state. No upstream ipfs_*_courts dataset exists for these countries."""
import sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_courthouses import *
NOT_COURT = re.compile(r"(?i)police|polic[ií]a|comisar[ií]a|carabinero|prison|c[aá]rcel|penitenciar|jail|fisca|prosecutor|procurad|ministerio p[uú]blico|ministry|notar|registro civil|registry of (?:births|deeds)|abogad|lawyer|attorney|\bbar association\b|colegio de|universit|school|escuela|embassy|embajada|consulado|municipalidad|alcald|ayuntamiento|hospital|\bbank\b|banco|检察|檢察|警察|監獄|监狱|法務部|地政|戶政|검찰|경찰|교도소|구치소|변호사|법무사|등기소|공증|clinic|church|iglesia|mosque|supermarket|hotel|restaurant|barbershop|pharmacy|farmacia|library|biblioteca|museum|museo|stadium|estadio|bomberos|fire station|\bdmv\b|probation|land registry|tax office|\binss\b|sii\b")
def B(cc, rows, spec):
    for bid, name, level, parent, *rest in spec:
        kw = rest[0] if rest else {}
        rows.append(body(cc, bid, name, level, parent, **kw))
    return rows
KEEP_ONLY = {}
def common(cc, bodies, classify, state_field=True, sys_of=None, default_note="court tier not classifiable from name"):
    rows = B(cc, [], bodies); ids = {r["court_id"] for r in rows}
    sec = osm_rows(cc) + (wd_rows(cc) if os.path.exists(f"{RD}/wd_{cc}.jsonl") else []); keep = []; drop = 0
    for s_ in sec:
        nm = s_["name"] or ""
        if not re.search(r"(?i)juzgado de polic|tribunal de polic", nm) and (NOT_COURT.search(nm) or NOT_COURT.search(s_.get("name_local") or "")): drop += 1; continue
        if cc in KEEP_ONLY and nm != "Courthouse" and not KEEP_ONLY[cc].search(nm + " " + (s_.get("name_local") or "")): drop += 1; continue
        g = s_["geo"]; c = nearest_city(g["lat"], g["lon"], cc) if g["lat"] is not None else None
        if c: s_["subdivision"] = f"{cc}-{c[3]}"
        if nm == "Courthouse": s_["needs_review"] = True; s_["record_note"] = "OSM courthouse without name"
        par = classify(" ".join(x for x in (nm, s_.get("name_local") or "") if x))
        if par and f"{cc.lower()}-{par}" in ids: s_["parent_court_id"] = f"{cc.lower()}-{par}"; s_["court_system"] = "national"
        else: s_["needs_review"] = True; s_["record_note"] = ((s_.get("record_note") or "") + " " + default_note).strip()
        keep.append(s_)
    print("non-court rows dropped", drop, "kept", len(keep), flush=True)
    rows = merge_sec(rows, keep, 120)
    print("places", dict(assign_places(rows, cc)), flush=True)
    a1 = gn_admin1(cc)
    for r in rows:
        if r["record_type"] == "court_body": r["place_ids"] = []; continue
        code = (r.get("subdivision") or "").split("-", 1)[-1]; nm = a1.get(code)
        sp = state_place(nm[0], cc) if nm else None
        if sp and sp not in r["place_ids"]: r["place_ids"] = r["place_ids"] + [sp]
    finish(cc, rows)
def has(p, s): return re.search(p, s, re.I)
# ---- TW
def tw_class(n):
    for p, b in ((r"憲法法庭|大法官|Constitutional", "constitutional-court"), (r"最高行政|Supreme Administrative", "supreme-administrative-court"), (r"高等行政|Higher Administrative|High Administrative|行政法院|Administrative Court", "high-administrative-court"),
                 (r"智慧財產|Intellectual Property", "ip-commercial-court"), (r"最高法院|Supreme Court", "supreme-court"), (r"少年及家事|Juvenile and Family|Family", "juvenile-family-court"), (r"高等法院|High Court", "high-court"), (r"地方法院|District Court|地院|法院", "district-court")):
        if has(p, n): return b
def tw():
    s = [("judicial-yuan", "Judicial Yuan", "national", None, dict(name_local="司法院")), ("constitutional-court", "Constitutional Court (Judicial Yuan)", "supreme", "judicial-yuan", dict(name_local="憲法法庭")), ("supreme-court", "Supreme Court", "supreme", "judicial-yuan", dict(name_local="最高法院")),
         ("supreme-administrative-court", "Supreme Administrative Court", "supreme", "judicial-yuan", dict(name_local="最高行政法院")), ("high-court", "High Court (and branches)", "appeal", "supreme-court", dict(name_local="高等法院")),
         ("high-administrative-court", "High Administrative Courts", "appeal", "supreme-administrative-court", dict(name_local="高等行政法院")), ("ip-commercial-court", "Intellectual Property and Commercial Court", "appeal", "supreme-court", dict(name_local="智慧財產及商業法院")),
         ("district-court", "District Courts (and branches)", "trial", "high-court", dict(name_local="地方法院")), ("juvenile-family-court", "Juvenile and Family Courts", "trial", "high-court", dict(name_local="少年及家事法院"))]
    common("TW", s, tw_class)
# ---- KR
def kr_class(n):
    for p, b in ((r"헌법재판소|Constitutional Court", "constitutional-court"), (r"대법원|Supreme Court", "supreme-court"), (r"특허법원|Patent Court", "patent-court"), (r"행정법원|Administrative Court", "administrative-court"), (r"회생법원|Bankruptcy Court", "bankruptcy-court"),
                 (r"가정법원|Family Court", "family-court"), (r"고등법원|High Court", "high-court"), (r"지방법원|지원|District Court|Branch Court|법원|Court", "district-court")):
        if has(p, n): return b
def kr():
    s = [("constitutional-court", "Constitutional Court of Korea", "supreme", None, dict(name_local="헌법재판소")), ("supreme-court", "Supreme Court of Korea", "supreme", None, dict(name_local="대법원")), ("patent-court", "Patent Court", "appeal", "supreme-court", dict(name_local="특허법원")),
         ("high-court", "High Courts (Seoul, Daejeon, Daegu, Busan, Gwangju, Suwon)", "appeal", "supreme-court", dict(name_local="고등법원")), ("district-court", "District Courts and branches", "trial", "high-court", dict(name_local="지방법원")),
         ("family-court", "Family Courts", "trial", "high-court", dict(name_local="가정법원")), ("administrative-court", "Seoul Administrative Court", "trial", "high-court", dict(name_local="행정법원")), ("bankruptcy-court", "Seoul Bankruptcy Court", "trial", "high-court", dict(name_local="회생법원"))]
    common("KR", s, kr_class)
# ---- PH
def ph_class(n):
    for p, b in ((r"Supreme Court", "supreme-court"), (r"Sandiganbayan", "sandiganbayan"), (r"Tax Appeals", "court-of-tax-appeals"), (r"Court of Appeals", "court-of-appeals"), (r"Shari.?a", "shariah-court"), (r"Regional Trial|\bRTC\b|Hall of Justice", "regional-trial-court"),
                 (r"Metropolitan Trial|Municipal Trial|Municipal Circuit|\bMTC|MeTC|MCTC|MTCC|Municipal Court|City Court", "metropolitan-trial-court"), (r"Court|Korte|Hukuman", "regional-trial-court")):
        if has(p, n): return b
def ph():
    s = [("supreme-court", "Supreme Court of the Philippines", "supreme", None), ("court-of-appeals", "Court of Appeals", "appeal", "supreme-court"), ("sandiganbayan", "Sandiganbayan", "appeal", "supreme-court"), ("court-of-tax-appeals", "Court of Tax Appeals", "appeal", "supreme-court"),
         ("shariah-court", "Shari'a Circuit and District Courts", "trial", "supreme-court"), ("regional-trial-court", "Regional Trial Courts", "trial", "court-of-appeals"), ("metropolitan-trial-court", "Metropolitan, Municipal Trial Courts and Municipal Circuit Trial Courts (first-level courts)", "trial", "regional-trial-court")]
    common("PH", s, ph_class)
# ---- AR
def ar_class(n):
    for p, b in ((r"Corte Suprema", "csjn"), (r"Casaci[oó]n", "camara-federal-casacion-penal"), (r"Superior Tribunal|Suprema Corte|Tribunal Superior de Justicia", "superior-tribunal-provincial"), (r"C[aá]mara Nacional.*Civil", "camara-nacional-civil"), (r"C[aá]mara Nacional.*Comercial", "camara-nacional-comercial"),
                 (r"C[aá]mara Federal", "camara-federal"), (r"Juzgado Federal|Justicia Federal|Tribunal Oral Federal|Poder Judicial de la Naci[oó]n", "juzgado-federal"), (r"Juzgado Nacional|Tribunales", "juzgado-nacional"), (r"Juzgado|Tribunal|Palacio de Justicia|Justicia|Poder Judicial|C[aá]mara|Fuero|Penal|Civil|Familia|Paz", "tribunal-provincial")):
        if has(p, n): return b
def ar():
    s = [("csjn", "Corte Suprema de Justicia de la Nación", "supreme", None), ("camara-federal-casacion-penal", "Cámara Federal de Casación Penal", "appeal", "csjn"), ("camara-federal", "Cámaras Federales de Apelaciones", "appeal", "csjn"), ("camara-nacional-civil", "Cámara Nacional de Apelaciones en lo Civil", "appeal", "csjn"),
         ("camara-nacional-comercial", "Cámara Nacional de Apelaciones en lo Comercial", "appeal", "csjn"), ("juzgado-federal", "Juzgados y Tribunales Federales", "trial", "camara-federal"), ("juzgado-nacional", "Juzgados Nacionales (Ciudad Autónoma de Buenos Aires)", "trial", "csjn"),
         ("superior-tribunal-provincial", "Superiores Tribunales / Cortes provinciales", "supreme", None, dict(system="state")), ("tribunal-provincial", "Tribunales y juzgados provinciales", "trial", "superior-tribunal-provincial", dict(system="state"))]
    common("AR", s, ar_class)
# ---- CO
def co_class(n):
    for p, b in ((r"Corte Suprema", "corte-suprema-de-justicia"), (r"Corte Constitucional", "corte-constitucional"), (r"Consejo de Estado", "consejo-de-estado"), (r"Consejo Superior de la Judicatura", "consejo-superior-de-la-judicatura"), (r"Tribunal Administrativo", "tribunal-administrativo"),
                 (r"Tribunal Superior", "tribunal-superior"), (r"Juzgado Administrativo", "juzgado-administrativo"), (r"Juzgado|Complejo Judicial|Palacio de Justicia|Ciudad Judicial|Casa de Justicia|Rama Judicial|Tribunal|Sala|Edificio|Centro de Servicios|Circuito|Municipal|Penal|Civil|Familia|Laboral", "juzgado")):
        if has(p, n): return b
def co():
    s = [("corte-suprema-de-justicia", "Corte Suprema de Justicia", "supreme", None), ("corte-constitucional", "Corte Constitucional", "supreme", None), ("consejo-de-estado", "Consejo de Estado", "supreme", None), ("consejo-superior-de-la-judicatura", "Consejo Superior de la Judicatura", "national", None),
         ("tribunal-superior", "Tribunales Superiores de Distrito Judicial", "appeal", "corte-suprema-de-justicia"), ("tribunal-administrativo", "Tribunales Administrativos", "appeal", "consejo-de-estado"), ("juzgado", "Juzgados de circuito y municipales (jurisdicción ordinaria)", "trial", "tribunal-superior"), ("juzgado-administrativo", "Juzgados Administrativos", "trial", "tribunal-administrativo")]
    common("CO", s, co_class)
# ---- CL
def cl_class(n):
    for p, b in ((r"Corte Suprema", "corte-suprema"), (r"Tribunal Constitucional", "tribunal-constitucional"), (r"Corte de Apelaciones", "corte-de-apelaciones"), (r"Polic[ií]a Local", "juzgado-de-policia-local"), (r"Garant[ií]a", "juzgado-de-garantia"), (r"Juicio Oral|\bTOP\b|Oral en lo Penal", "tribunal-de-juicio-oral-en-lo-penal"), (r"Familia", "juzgado-de-familia"),
                 (r"Cobranza", "juzgado-de-cobranza-laboral"), (r"del Trabajo|Laboral", "juzgado-de-letras-del-trabajo"), (r"Letras|Civil|Juzgado|Palacio|Tribunales|Tribunal|Poder Judicial", "juzgado-civil")):
        if has(p, n): return b
def cl():
    s = [("corte-suprema", "Corte Suprema de Chile", "supreme", None), ("tribunal-constitucional", "Tribunal Constitucional", "supreme", None), ("corte-de-apelaciones", "Cortes de Apelaciones", "appeal", "corte-suprema"), ("juzgado-civil", "Juzgados de Letras / Civiles", "trial", "corte-de-apelaciones"),
         ("juzgado-de-garantia", "Juzgados de Garantía", "trial", "corte-de-apelaciones"), ("tribunal-de-juicio-oral-en-lo-penal", "Tribunales de Juicio Oral en lo Penal", "trial", "corte-de-apelaciones"), ("juzgado-de-familia", "Juzgados de Familia", "trial", "corte-de-apelaciones"),
         ("juzgado-de-letras-del-trabajo", "Juzgados de Letras del Trabajo", "trial", "corte-de-apelaciones"), ("juzgado-de-cobranza-laboral", "Juzgados de Cobranza Laboral y Previsional", "trial", "corte-de-apelaciones"), ("juzgado-de-policia-local", "Juzgados de Policía Local (municipal courts of minor offences)", "trial", "corte-de-apelaciones")]
    common("CL", s, cl_class)
# ---- NG
def ng_class(n):
    for p, b in ((r"Supreme Court", "supreme-court"), (r"Court of Appeal", "court-of-appeal"), (r"Sharia Court of Appeal", "sharia-court-of-appeal"), (r"National Industrial", "national-industrial-court"), (r"Federal High Court|\bFHC\b", "federal-high-court"), (r"\bFCT\b|Abuja.*High Court|High Court.*Abuja|Federal Capital", "fct-high-court"),
                 (r"Magistrate|District Court", "magistrate-court"), (r"Customary|Area Court|Sharia", "customary-court"), (r"High Court|Court of Justice|Judiciary|Law Courts|Court", "state-high-court")):
        if has(p, n): return b
def ng():
    s = [("supreme-court", "Supreme Court of Nigeria", "supreme", None), ("court-of-appeal", "Court of Appeal", "appeal", "supreme-court"), ("sharia-court-of-appeal", "Sharia Courts of Appeal", "appeal", "supreme-court", dict(system="state")), ("federal-high-court", "Federal High Court", "trial", "court-of-appeal"),
         ("national-industrial-court", "National Industrial Court", "trial", "court-of-appeal"), ("fct-high-court", "High Court of the Federal Capital Territory", "trial", "court-of-appeal"), ("state-high-court", "State High Courts", "trial", "court-of-appeal", dict(system="state")),
         ("magistrate-court", "Magistrate and District Courts", "trial", "state-high-court", dict(system="state")), ("customary-court", "Customary and Area Courts", "trial", "state-high-court", dict(system="state"))]
    common("NG", s, ng_class)
# ---- KE
def ke_class(n):
    for p, b in ((r"Supreme Court", "supreme-court"), (r"Court of Appeal", "court-of-appeal"), (r"Environment and Land|\bELC\b", "environment-and-land-court"), (r"Employment and Labour|\bELRC\b", "employment-and-labour-relations-court"), (r"Kadhi", "kadhis-court"),
                 (r"Small Claims", "small-claims-court"), (r"High Court", "high-court"), (r"Magistrate|Law Courts|Court", "magistrates-court")):
        if has(p, n): return b
def ke():
    s = [("supreme-court", "Supreme Court of Kenya", "supreme", None), ("court-of-appeal", "Court of Appeal", "appeal", "supreme-court"), ("high-court", "High Court", "trial", "court-of-appeal"), ("environment-and-land-court", "Environment and Land Court", "trial", "court-of-appeal"),
         ("employment-and-labour-relations-court", "Employment and Labour Relations Court", "trial", "court-of-appeal"), ("magistrates-court", "Magistrates' Courts", "trial", "high-court"), ("kadhis-court", "Kadhis' Courts", "trial", "high-court"), ("small-claims-court", "Small Claims Courts", "trial", "high-court")]
    common("KE", s, ke_class)
BUILD.update({"TW": tw, "KR": kr, "PH": ph, "AR": ar, "CO": co, "CL": cl, "NG": ng, "KE": ke})
if __name__ == "__main__":
    for cc in sys.argv[1:]: BUILD[cc]()
