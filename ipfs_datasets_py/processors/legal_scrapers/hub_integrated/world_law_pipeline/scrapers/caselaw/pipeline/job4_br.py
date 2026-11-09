"""Job 4: Brazil STJ 'Espelhos de acordaos - Terceira Turma' (dadosabertos.web.stj.jus.br, CKAN portal, licence shown on dataset page: Creative Commons Atribuicao).
ONE polite attempt: dataset HTML page + data dictionary + ONE monthly JSON (20260131.json) fetched with 10 s crawl-delay; /api/ never used (robots Disallow).
This script only parses the already-downloaded sample in $IPFS_DATASETS_LEGAL_WORKSPACE/case_law/br_probe/ (no network). Text = ementa + decisao (espelho, NOT full inteiro teor)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys, json
from cl_common import *
SRC = "br_stj_dados_abertos"
PAGE = "https://dadosabertos.web.stj.jus.br/dataset/espelhos-de-acordaos-terceira-turma"
FILE = (str(_LEGAL_WS) + "/case_law/br_probe/20260131.json")
LICENCE = "Creative Commons Atribuicao (Attribution), as stated on the dataset page (licence version not specified; link to opendefinition.org/licenses/cc-by); attribution to STJ required"
TERMS = {"basis": "Licence field on the STJ open-data dataset page: 'Licenca Creative Commons Atribuicao'. robots.txt: crawl-delay 10 s, /api/ disallowed (not used). Data = espelho (ementa + decisao), not full inteiro teor. Personal-data / anonymisation status not verified.",
         "evidence_url": [PAGE, "https://dadosabertos.web.stj.jus.br/robots.txt"], "checked": "2026-10-29", "pending_legal_review": True, "attribution": "Superior Tribunal de Justica (STJ) - Portal de Dados Abertos"}
def clean(t):
    t = re.sub(r"[ \t\r\f\v\u00a0]+", " ", t or ""); t = re.sub(r" ?\n ?", "\n", t); return re.sub(r"\n{3,}", "\n\n", t).strip()
def main():
    print(now_la(), "start", preflight("start"), flush=True)
    data = json.load(open(FILE, encoding="utf8"))
    out = SourceOut(SRC, max_rows=500); matcher = CourtMatcher(); fails = []; skipped = {}
    for r in data:
        rid = str(r.get("id") or "")
        if not rid or rid in out.seen: skipped["dup_or_noid"] = skipped.get("dup_or_noid", 0) + 1; continue
        text = clean("\n\n".join(x for x in [r.get("ementa"), r.get("decisao")] if x))
        if len(text) < 200: skipped["no_short_text"] = skipped.get("no_short_text", 0) + 1; continue
        d = str(r.get("dataDecisao") or ""); date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d) else None
        date = date if date and cs.RE_DATE.match(date) else None
        dt = (r.get("tipoDeDecisao") or "").upper()
        dtype = "judgment" if dt.startswith("AC") else ("ruling" if "DECIS" in dt else "other")
        docket = " ".join(x for x in [r.get("siglaClasse"), r.get("numeroProcesso")] if x) or None
        nm = "Superior Tribunal de Justiça"
        cm = matcher.match("BR", nm, admin1=None, source_name=SRC, discriminator="STJ")
        base = lambda k, r_: common_row(k, source_name=SRC, source_type="ckan_dataset_json", rec_id=r_, country_iso="BR", level="national", juris_raw="BR", admin1=None, url=PAGE,
                                        phase="phaseA", source_file="espelhos-de-acordaos-terceira-turma/20260131.json", licence=LICENCE, licence_class="open", fetch_mode="bulk")
        dec = base("decision", rid)
        dec.update(court_entity_key=cm["court_entity_key"], court_key_provisional=cm["court_key_provisional"], court_match_status=cm["court_match_status"], court_name_raw=nm,
                   docket_number=docket, decision_date=date, canonical_key=None, decision_type=dtype, language="pt", opinion_count=1, restricted_ai_training=True, ocr=False,
                   text_sha256=cs.text_sha256(text), parties_redaction_status="unknown",
                   metadata_json={"terms": TERMS, "orgao_julgador": r.get("nomeOrgaoJulgador"), "classe": r.get("descricaoClasse"), "numero_registro": r.get("numeroRegistro"),
                                  "data_publicacao": r.get("dataPublicacao"), "courts_dataset_revision": cs.COURTS_DATASET_REVISION, **cm["meta"]})
        op = base("opinion", rid + "#lead")
        op.update(decision_id=dec["id"], opinion_type="other", text=text, text_format="plain", ocr=False, text_backend="stj_json_ementa_decisao", text_sha256=cs.text_sha256(text),
                  restricted_ai_training=True, parties_redaction_status="unknown", language="pt", metadata_json={"terms": TERMS})
        if not out.add_pair(dec, op): fails.append((rid, "rejected by row validation")); continue
        out.seen.add(rid)
    for rec in out.flush(): print(now_la(), "shard", rec, flush=True)
    up = dump_unmatched(SRC, matcher)
    s = write_summary(SRC, courts=1, fails=fails[:50], n_fails=len(fails), skipped_this_run=skipped, http_requests=3, rows_this_run=out.rows, shards_this_run=out.shards, bytes_this_run=out.bytes,
                      court_match_stats_this_run=matcher.stats, unmatched_file=up, end_gate=preflight("end"), finished_la=now_la(), note="one monthly file only (2026-01-31 release, Terceira Turma); robots crawl-delay 10 s honoured")
    print(json.dumps(s, indent=1), flush=True)
if __name__ == "__main__":
    try: main()
    except StopJob as e: print(now_la(), str(e), flush=True); sys.exit(3)
