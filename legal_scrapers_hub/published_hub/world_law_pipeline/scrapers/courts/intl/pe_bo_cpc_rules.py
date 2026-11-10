"""PE: TUO Código Procesal Civil (R.M. 010-93-JUS), El Peruano 'Normas Legales Actualizadas' PDF (diariooficial.elperuano.pe, unreachable from box) via Wayback 20250410222327.
   (congreso.gob.pe copy NOT used: robots Disallow / for *.)
BO: Ley 439 Código Procesal Civil (2013), PDF from Escuela de Jueces del Estado (backend.academico.eje.gob.bo). One row per artículo; never overwrites."""
import json, sys, re, datetime, hashlib, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
now = datetime.datetime.now(datetime.UTC).isoformat()
CFG = {
 "pe": dict(pdf="pe_rules/tuo_cpc.pdf", txt="pe_rules/tuo_cpc_r.txt", rx=r"^Artículo ([0-9]+|[IVX]+)[º°]?\.-\s*(.*)$", sid="pe-cpc-tuo-1993",
   rs="Texto Único Ordenado del Código Procesal Civil (D.Leg. 768; R.M. 010-93-JUS), texto actualizado — Editora Perú / El Peruano", eff="1993-07-28",
   src="https://diariooficial.elperuano.pe/Normas/obtenerDocumento?idNorma=120007", pol="archived_copy(wayback:20250410222327);origin_unreachable",
   lic="Peruvian legal norms are excluded from copyright (D.Leg. 822 art. 9)", skip_first=2),
 "bo": dict(pdf="bo_rules/cpc.pdf", txt="bo_rules/cpc_r.txt", rx=r"^\s*ARTÍCULO ([0-9]+)\.\s*(.*)$", sid="bo-cpc-ley439-2013",
   rs="Código Procesal Civil, Ley N° 439 de 19 de noviembre de 2013 (Gaceta Oficial 585NEC)", eff="2016-02-06",
   src="https://backend.academico.eje.gob.bo/files/recursos/C%C3%93DIGO_PROCESAL_CIVIL_LEY_N_439.pdf", pol="robots_none(no robots.txt);official:Escuela de Jueces del Estado",
   lic="Bolivian laws are public (Ley 1322 art. 8 excludes official texts)", skip_first=0),
 "hn": dict(pdf="hn_rules/cpc.pdf", txt="hn_rules/cpc.txt", rx=r"^Artículo ([0-9]+)\.-?\s*(.*)$", sid="hn-cpc-211-2006", mono=True,
   rs="Código Procesal Civil, Decreto No. 211-2006 (actualizado), CEDIJ Poder Judicial de Honduras", eff="2010-05-01",
   src="https://www.poderjudicial.gob.hn/Cedij/Cdigos/Codigo%20Procesal%20Civil%20(2018).pdf", pol="robots_allowed;official:CEDIJ Poder Judicial",
   lic="Honduran laws are public (Ley del Derecho de Autor art. 11)", skip_first=0),
 "sv": dict(pdf="sv_rules/cpcm.pdf", txt="sv_rules/cpcm.txt", rx=r"^Art\. ?([0-9]+)\.-\s*(.*)$", sid="sv-cpcm-712-2008", mono=True,
   rs="Código Procesal Civil y Mercantil, Decreto Legislativo No. 712 (2008), edición CNJ 2025", eff="2010-07-01",
   src="https://www.cnj.gob.sv/images/documentos/pdf/ecj/publicaciones/C%C3%93DIGO%20PROCESAL%20CIVIL%20Y%20MERCANTIL%202025.pdf", pol="archived_copy(wayback:20251114081344);origin_403",
   lic="Salvadoran laws are not protected (Ley de Propiedad Intelectual art. 13)", skip_first=0),
 "pa": dict(pdf="pa_rules/cpc.pdf", txt="pa_rules/cpc.txt", rx=r"^Artículo ([0-9]+)\.\s*(.*)$", sid="pa-cpc-ley402-2023", mono=True,
   rs="Código Procesal Civil de la República de Panamá, Ley 402 de 9 de octubre de 2023 (Gaceta Oficial 29887-A)", eff="2025-10-11",
   src="http://gacetas.procuraduria-admon.gob.pa/29887-A_2023.pdf", pol="archived_copy(wayback:20251118224208);origin_unreachable",
   lic="Panamanian official texts excluded from copyright (Ley 64 de 2012 art. 9)", skip_first=0),
 "do": dict(pdf="do_rules/cpc.pdf", txt="do_rules/cpc.txt", rx=r"^Artículo ([0-9]+)\.-\s*(.*)$", sid="do-cpc-2023", mono=True,
   rs="Ley del Código de Procedimiento Civil de la República Dominicana (texto del Congreso Nacional, Memoria Histórica del Senado)", eff=None,
   src="https://memoriahistorica.senadord.gob.do/bitstreams/65e2d54d-c21c-4703-b456-e338073d4ae3/download", pol="robots_allowed;official:Senado RD",
   lic="Dominican laws are not protected (Ley 65-00 art. 11)", skip_first=0),
 "py": dict(pdf="py_rules/cpc.pdf", txt="py_rules/cpc.txt", rx=r"^Art\. ?([0-9]+)\s*[o°º]?\.?-?\s*(.*)$", sid="py-cpc-ley1337-1988", mono=True,
   rs="Código Procesal Civil, Ley N° 1337 de 4 de noviembre de 1988", eff="1989-11-04",
   src="https://correoparaguayo.gov.py/sitio/wp-content/uploads/2023/09/Codigo-Procesal-Civil-1988.pdf", pol="robots_none(404);official:Dirección Nacional de Correos del Paraguay (gov.py)",
   lic="Paraguayan laws are not protected (Ley 1328/98 art. 8)", skip_first=0),
 "cr": dict(pdf="cr_rules/cpc1.html", txt="cr_rules/cpc.txt", rx=r"^ART[IÍ]CULO ([0-9]+)\.-\s*(.*)$", sid="cr-cpc-ley9342-2016", mono=True,
   rs="Código Procesal Civil, Ley N° 9342 de 3 de febrero de 2016 (texto original, versión 1 SCIJ/PGR)", eff="2018-10-08",
   src="http://www.pgrweb.go.cr/TextoCompleto/NORMAS/1/VIGENTE/L/2010-2019/2015-2019/2016/13DD0/81360_103729-1.html", pol="archived_copy(wayback:20220703185231);origin_unreachable",
   lic="Costa Rican laws are not protected (Ley 6683 art. 75)", skip_first=0),
 "ni": dict(pdf="ni_rules/cpc.pdf", txt="ni_rules/cpc.txt", rx=r"^Artículo ([0-9]+)\s+(.*)$", sid="ni-cpc-ley902-2015", mono=True,
   rs="Código Procesal Civil de la República de Nicaragua, Ley N° 902 (La Gaceta No. 191, 9 de octubre de 2015)", eff="2017-04-09",
   src="https://www.poderjudicial.gob.ni/pjupload/leyes/ley-902-codigo-procesal-civil.pdf", pol="archived_copy(wayback:20250523055403);origin_unreachable",
   lic="Nicaraguan laws are not protected (Ley 312 art. 13)", skip_first=0),
 "vn": dict(pdf="vn_rules/vbhn99.pdf", txt="vn_rules/vbhn99.txt", rx=r"^Điều ([0-9]+)\.\s*(.*)$", sid="vn-bltdds-2015-vbhn99", mono=True, lang="vi",
   rs="Bộ luật Tố tụng dân sự (Luật số 92/2015/QH13), Văn bản hợp nhất số 99/VBHN-VPQH ngày 26/08/2025", eff="2016-07-01",
   src="https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/9/99-vbhn-vpqh.pdf", pol="robots_unknown(robots.txt 403);official:Cổng TTĐT Chính phủ (chinhphu.vn)",
   lic="Vietnamese legal normative documents are not protected (Law on IP 2005 art. 15)", skip_first=0)}

CFG["cu"]=dict(pdf="cu_rules/cp.pdf", txt="cu_rules/cp.txt", rx=r"^Artículo ([0-9]+)\.\s*(.*)$", sid="cu-cp-ley141-2021", mono=True,
   rs="Ley No. 141/2021 Código de Procesos (Gaceta Oficial No. 138 Ordinaria, 7 de diciembre de 2021), PDF del Tribunal Supremo Popular", eff="2022-01-01",
   src="https://www.tsp.gob.cu/sites/default/files/documentos/C%C3%B3digo%20de%20Procesos.pdf", pol="robots_allowed;official:Tribunal Supremo Popular (gacetaoficial.gob.cu 403)",
   lic="Cuban legal norms are excluded from copyright (Decreto-Ley 371/2018 art. 6)", skip_first=0)
CFG["ht"]=dict(pdf="ht_rules/cpc1963.txt", txt="ht_rules/cpc1963.txt", rx=r"^\s*Article\s+([0-9]+)(?:er)?\s*\.?\s*[—-]+\s*(.*)$", sid="ht-cpc-1963", mono=True, lang="fr",
   rs="Code de procédure civile d'Haïti, voté le 17 septembre 1963 (Impr. de l'État, 1965) — OCR Internet Archive / Library of Congress", eff="1964-04-01",
   src="https://archive.org/details/codedeprocdure00hait", pol="robots_allowed;archive.org(Library of Congress: no known copyright restrictions);ocr_text_needs_review",
   lic="Public domain (official Haitian legislative text; LoC: no known copyright restrictions)", skip_first=0)
import sys as _s
if len(_s.argv) > 1: CFG = {k: v for k, v in CFG.items() if k in _s.argv[1].split(",")}
for cc, c in CFG.items():
    OUT = f"{ROOT}/data/{cc}/{cc}_rules.jsonl"; old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
    sha = hashlib.sha256(open(f"{ROOT}/rules/raw/{c['pdf']}", "rb").read()).hexdigest(); secs = []; cur = None; n = 0
    for l in open(f"{ROOT}/rules/raw/{c['txt']}", encoding="utf-8"):
        s = l.strip()
        if not s or re.fullmatch(r"\d+|Inicio|NORMAS LEGALES ACTUALIZADAS|TUO del Código Procesal Civil|www\..*", s): continue
        m = re.match(c["rx"], l)
        if m and c.get("mono"):
            k = int(m.group(1)); last = int(secs[-1][0]) if secs else 0
            if not (last < k <= last + 15): m = None
        if m:
            n += 1
            if n <= c["skip_first"]: cur = None; continue
            cur = [m.group(1), m.group(2)]; secs.append(cur); continue
        if re.match(r"^(SECCIÓN|TÍTULO|CAPÍTULO|Capítulo|Subcapítulo|LIBRO|TITULO|CAPITULO)\b", s): continue
        if cur: cur[1] += " " + s
    rows, seen = [], set()
    for num, txt in secs:
        rid = f"{c['sid']}:art-{num.lower()}"
        if rid in seen or rid in old: continue
        seen.add(rid); txt = re.sub(r"\s+", " ", txt).strip()
        tm = re.match(r"^\(([^)]{2,120})\)\.?\s*(.*)$", txt) if cc == "bo" else None
        rows.append({"rule_id": rid, "rule_set_id": c["sid"], "court_id": None, "jurisdiction": cc.upper(), "rule_set": c["rs"], "rule_number": f"Artículo {num}",
          "title": tm.group(1) if tm else None, "text": tm.group(2) if tm else txt, "effective_date": c["eff"], "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha,
          "source_url": c["src"], "site_policy": c["pol"], "retrieved_at": now, "license": c["lic"], "language": c.get("lang", "es"),
          "record_note": "Título Preliminar" if re.fullmatch(r"[IVX]+", num) else None})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(cc, "matched", len(secs), "added", len(rows), "|", rows[3]["rule_number"], rows[3]["text"][:100])
