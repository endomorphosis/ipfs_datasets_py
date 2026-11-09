"""Portuguese procedural codes. The official DRE (diariodarepublica.pt / data.dre.pt) is a JS app with no open text endpoint, so the consolidated texts come from the Procuradoria-Geral Distrital
de Lisboa legislation compilation (www.pgdlisboa.pt, a public-prosecutor body; consolidated Diario da Republica texts) -- flagged site_policy=secondary_state_body, NOT the DRE original. -> data/pt/pt_rules.jsonl"""
import sys, hashlib, html as H
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW
CODES = [("pt-cpc", "Código de Processo Civil (Lei n.º 41/2013)", 1959), ("pt-cpp", "Código de Processo Penal (DL n.º 78/87)", 199)]
def clean(s):
    s = re.sub(r"(?i)<br\s*/?>", " ", s); s = re.sub(r"<[^>]+>", " ", s); return re.sub(r"\s+", " ", H.unescape(s).replace("\xa0", " ")).strip()
def main():
    rows = []
    for sid, name, nid in CODES:
        n = 0; seen = {}; sha_all = hashlib.sha256()
        for k in range(0, 40):
            p = f"{RAW}/intl_pt_pgdl_{nid}_{k}.html"; url = f"https://www.pgdlisboa.pt/leis/lei_mostra_articulado.php?nid={nid}&tabela=leis&artigo_id=&ficha={1 + 100 * k}&pagina={k + 1}&nversao=&so_miolo="
            if not os.path.exists(p):
                time.sleep(2.0)
                try: open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90).read())
                except Exception as e: print("miss", sid, k, e); break
            raw = open(p, "rb").read(); sha_all.update(raw); h = raw.decode("latin1")
            pat = re.compile(r"font-weight:bold;color:#d74600[^>]*>(?:&nbsp;)*\s*(Artigo[^<]*?)<br>\s*([^<]*)</td>", re.S)
            ms = list(pat.finditer(h))
            if not ms: break
            for i, m in enumerate(ms):
                end = h.find("<!-- IN", m.end()); nxt = ms[i + 1].start() if i + 1 < len(ms) else len(h)
                seg = h[m.end(): min(x for x in (end if end > 0 else nxt, nxt))]
                text = clean(seg)
                lab = clean(m.group(1)); num = re.sub(r"\s*\(.*$", "", lab).strip(); title = clean(m.group(2)) or None
                if len(text) < 8: continue
                seen[num] = seen.get(num, 0) + 1
                rows.append(dict(rule_id=f"{sid}:{num}" + (f"~{seen[num]}" if seen[num] > 1 else ""), rule_set_id=sid, court_id=None, jurisdiction="PT", rule_set=name, rule_number=num, title=title, text=text, effective_date=None,
                                 pdf_path=None, pdf_sha256=None, source_sha256=None, source_url=f"https://www.pgdlisboa.pt/leis/lei_mostra_articulado.php?nid={nid}&tabela=leis", site_policy="secondary_state_body:pgdlisboa (DRE is JS-only)",
                                 retrieved_at=NOW(), license="Portuguese official legislation (CDADC art. 7: legal texts not protected); compilation by PGDL", language="pt", _sha=None)); n += 1
        for r in rows:
            if r["rule_set_id"] == sid: r["source_sha256"] = sha_all.hexdigest(); r.pop("_sha", None)
        print(sid, n, flush=True)
    os.makedirs(f"{ROOT}/data/pt", exist_ok=True); wjl(f"{ROOT}/data/pt/pt_rules.jsonl", rows); print("PT rules", len(rows))
if __name__ == "__main__": main()
