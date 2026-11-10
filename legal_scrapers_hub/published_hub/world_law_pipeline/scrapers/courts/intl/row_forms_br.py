"""Brazil forms: TJSP Juizados Especiais petition templates (official tjsp.jus.br; state court, tagged) + JEC form. 'Roteiro'/guide/FAQ/charter items rejected -> data/br/br_rejected_brochures.jsonl.
-> forms/br/<sha>.<ext>, data/br/br_forms.jsonl"""
import sys, hashlib, urllib.parse, html
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import polite_get
IDX = "https://portal.tjsp.jus.br/PeticionamentoJEC/PeticionamentoJEC/ModelosPeticoes"
BAD = re.compile(r"roteiro|faq|carta de servi|enunciado|regimento|regulamento|s[uú]mula|escala|comunicado|endere[cç]os|cejusc|guia|cartilha|manual|folder|cartaz", re.I)
def main():
    os.makedirs(f"{ROOT}/forms/br", exist_ok=True); b, u, pol = polite_get(IDX, delay=2); h = b.decode("utf-8", "ignore") if isinstance(b, bytes) else b
    items = [(urllib.parse.urljoin(IDX, a), html.unescape(re.sub(r"\s+", " ", t)).strip()) for a, t in re.findall(r'href="([^"]+\.(?:pdf|docx?|odt|rtf))"[^>]*>([^<]*)', h, re.I) if "/ModelosPeticoes/" in a]
    items.append(("https://www.tjsp.jus.br/Download/JuizadosEspeciais/FormularioJEC.pdf", "Formulário do Juizado Especial Cível (atendimento)")); seen = set(); out = []; rej = []
    for href, title in items:
        if href in seen: continue
        seen.add(href)
        if BAD.search(title) or BAD.search(href.rsplit("/", 1)[-1]): rej.append(dict(title=title, source_url=href, reason="guide/roteiro/regulation/other non-form document")); continue
        d, eu, p2 = polite_get(href, delay=2.0, binary=True)
        if not d or len(d) < 500: continue
        ext = re.search(r"\.(pdf|docx?|odt|rtf)$", href, re.I).group(1).lower(); sh = hashlib.sha256(d).hexdigest(); path = f"forms/br/{sh}.{ext}"
        if not os.path.exists(f"{ROOT}/{path}"): open(f"{ROOT}/{path}", "wb").write(d)
        if any(o["pdf_sha256"] == sh for o in out): continue
        out.append(dict(form_id=f"br-{sh[:16]}", court_id="br-sp-appellate-tjsp", jurisdiction="BR", form_number=None, title=title, category="Juizados Especiais (TJSP) - modelos de petição", language="pt", file_format=ext, pdf_path=path, pdf_sha256=sh, file_bytes=len(d), source_url=eu, index_url=IDX,
                        license="Tribunal de Justiça do Estado de São Paulo public website; official templates, reuse per site terms", site_policy=p2 + "|state_body_secondary", retrieved_at=NOW()))
    os.makedirs(f"{ROOT}/data/br", exist_ok=True); wjl(f"{ROOT}/data/br/br_forms.jsonl", out); wjl(f"{ROOT}/data/br/br_rejected_brochures.jsonl", rej); print("BR forms", len(out), "rejected", len(rej))
    for r in rej: print(" rej:", r["title"][:70])
if __name__ == "__main__": main()
