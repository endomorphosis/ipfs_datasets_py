#!/usr/bin/env python3
"""README / MANIFEST / triage JSONs / gap list for the DE subnational staging. Usage: de_report.py <stage dir>"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, json, time, re
from pathlib import Path
S = Path(sys.argv[1]); B = Path('{_CORPORA}/de_subnational'); T = Path('/workspace/country-law-triage'); T.mkdir(exist_ok=True)
J = lambda p: json.load(open(p))
chk = J(B / 'stage_check.json'); bchk = J(B / 'build_checks.json'); brep = J(B / 'build' / 'build_report.json'); blk = J(B / 'blocked.json')
col = J(B / 'collect_result_combined.json')['result'] if (B / 'collect_result_combined.json').exists() else J(B / 'collect_result_full.json')['result']; sup = J(B / 'collect_result_supplement.json')['result'] if (B / 'collect_result_supplement.json').exists() else {}
hc = J(B / 'handcheck_staged.json'); hpre = J(B / 'handcheck_prerun.json'); spot = J(B / 'spotcheck_staged.json')
per = chk['post']['per_jurisdiction']; bper = bchk['per_jurisdiction']
NAMES = {'BW': 'Baden-Württemberg', 'BY': 'Bayern', 'BE': 'Berlin', 'BB': 'Brandenburg', 'HB': 'Bremen', 'HH': 'Hamburg', 'HE': 'Hessen', 'MV': 'Mecklenburg-Vorpommern',
         'NI': 'Niedersachsen', 'NW': 'Nordrhein-Westfalen', 'RP': 'Rheinland-Pfalz', 'SL': 'Saarland', 'SN': 'Sachsen', 'ST': 'Sachsen-Anhalt', 'SH': 'Schleswig-Holstein', 'TH': 'Thüringen'}
PORTAL = {'NW': 'https://recht.nrw.de', 'SN': 'https://www.revosax.sachsen.de', 'HB': 'https://www.transparenz.bremen.de/vorschriften-72741', 'BB': 'https://bravors.brandenburg.de'}
LIC = {
 'NW': 'Gesetze/Verordnungen are amtliche Werke, public domain under § 5 Abs. 1 UrhG. recht.nrw.de (Ministerium des Innern NRW) publishes non-official consolidated reading versions ("nichtamtliche bereinigte Fassungen"); Impressum contains only liability disclaimers, no reuse licence, no TDM reservation found, robots.txt "Allow: /". A database right of the Land (§ 87a ff. UrhG) in the portal database as a whole cannot be excluded.',
 'SN': 'Public domain under § 5 Abs. 1 UrhG. REVOSax (Sächsische Staatskanzlei, built with SV SAXONIA Verlag GmbH); Impressum = liability disclaimer only; no reuse licence or TDM reservation found; robots.txt has no rule for generic agents. Possible § 87a ff. database right of the operator in the database as a whole.',
 'HB': 'Public domain under § 5 Abs. 1 UrhG for the statute texts. Transparenzportal Bremen Nutzungsbedingungen: data may be used "für alle Zwecke" if terms and law are respected, with attribution "<Verantwortliche Stelle>, Freie Hansestadt Bremen"; BUT every document in the Vorschriften database is labelled "CC Namensnennung - Nicht-kommerziell - Keine Bearbeitung" (CC BY-NC-ND) and the texts are juris-produced (juris-Abkürzung, juris doc numbers). The CC label cannot restrict § 5 texts themselves but may be asserted over the editorial/database layer (§ 87a ff.). CoS/legal decision needed before publishing DE-HB; if published: attribute and note NC-ND.',
 'BB': 'Public domain under § 5 Abs. 1 UrhG. BRAVORS (Land Brandenburg) Nutzungshinweise describe content/search only; no licence or TDM reservation found. robots.txt Crawl-delay 20 respected (one request per 20 s). Possible § 87a ff. database right of the Land in the database as a whole.',
 'NI': 'NOT COLLECTED. NI-VORIS (hosted by Wolters Kluwer Deutschland GmbH) Nutzungsvorbehalt: reservation of text-and-data-mining rights under § 44b Abs. 3 UrhG for all works incl. databases; reproduction/extraction for commercial TDM not permitted. § 5 UrhG covers the statute texts, but the TDM reservation and database right (§ 87a ff.) of the host block automated collection without permission.',
 'BW': 'NOT COLLECTED. landesrecht-bw.de (juris GmbH for the Land) robots.txt disallows all generic agents. Terms of use not retrieved; juris-hosted portals typically assert database rights (§ 87a ff. UrhG) over the consolidated database. Statute texts themselves are § 5 public domain.',
 'BY': 'NOT COLLECTED. gesetze-bayern.de returned HTTP 503 "Security Check" (myracloud) 3x; terms of use not retrieved. Statute texts § 5 public domain; database right of the operator possible.',
}
for l in ['BE', 'HH', 'HE', 'MV', 'RP', 'SL', 'ST', 'SH', 'TH']:
    LIC[l] = 'NOT COLLECTED. juris-hosted Landesrecht portal unreachable from our egress (TLS reset, BLOCKED_SOURCE); terms of use could not be retrieved. juris-hosted portals typically assert database rights (§ 87a ff. UrhG) and restrict automated/systematic retrieval in their Nutzungsbedingungen (not verified here). Statute texts themselves are § 5 public domain.'
lands_c = [l for l in ['BB', 'HB', 'NW', 'SN'] if f'DE-{l}' in per]
def row(l):
    p = per.get(f'DE-{l}', {}); q = bper.get(f'DE-{l}', {})
    return p, q
# ---- gap list
gaps = {'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'lands': {}}
for l, nm in NAMES.items():
    d = {'name': nm}
    if l in lands_c:
        p, q = row(l); d.update(status='COLLECTED', portal=PORTAL[l], laws=p.get('laws'), articles=p.get('articles'),
            collector=dict(col.get(l, {}), supplement=sup.get(l)),
            excluded_by_build={k[len(l) + 1:]: v for k, v in brep.items() if k.startswith(l + '_excluded')},
            known_gaps={'NW': ['Verwaltungsvorschriften (lrmb, ~4.9k) and Bekanntmachungen not collected (scope: Gesetze + Rechtsverordnungen)', 'laws whose current Fassung is not in the portal sitemap and not linked from any fetched page'],
                        'SN': ['Verwaltungsvorschriften, Richtlinien, Förderrichtlinien, Bekanntmachungen, Berichtigungen, Änderungs-/Aufhebungsvorschriften excluded (sitemap slug prefilter + meta doc type)', 'only laws listed in the REVOSax sitemap.xml'],
                        'HB': ['only "Gesetze und Rechtsverordnungen" with Gültigkeit "In Kraft"; Verwaltungsvorschriften, Satzungen, Staatsverträge (separate facet), Rundschreiben not collected', 'includes Ortsgesetze/Ortsrecht of the Stadtgemeinde Bremen (municipal level) because the portal files them under Gesetze und Rechtsverordnungen'],
                        'BB': ['only /gesetze/ and /verordnungen/ entries linked from the chronological Fundstellennachweis; Staatsverträge (/vertraege/) and Verwaltungsvorschriften not collected', 'crawl-delay 20 s']}[l])
    else:
        b = blk['blocked'].get(f'DE-{l}', {}); d.update(status=b.get('status') or blk['juris_edge_block']['status'], portal=b.get('portal'), reason=b.get('reason') or blk['juris_edge_block']['reason'], evidence=b.get('evidence') or {k: blk['juris_edge_block'][k] for k in ('attempts_pt', 'evidence_files')})
    gaps['lands'][f'DE-{l}'] = d
json.dump(gaps, open(T / 'germany_subnational_gap_list.json', 'w'), indent=1, ensure_ascii=False)
# ---- checks
checks = {'generated_at': gaps['generated_at'], 'stage': str(S), 'never_thin_precheck': {k: chk[k] for k in ('PASS', 'tip_unchanged', 'live_tip', 'laws', 'articles', 'id_collisions_skipped', 'files_removed', 'files_added', 'federal_before', 'federal_after', 'laws_snapshot_matches_live', 'articles_snapshot_matches_live')},
          'post_stage': chk['post'], 'build_checks': bchk, 'handcheck_prerun': {'pass': sum(r['PASS'] for r in hpre), 'n': len(hpre), 'rows': hpre},
          'handcheck_staged': {'pass': sum(r['PASS'] for r in hc), 'n': len(hc), 'rows': hc}, 'spotcheck_staged': spot}
json.dump(checks, open(T / 'germany_subnational_checks.json', 'w'), indent=1, ensure_ascii=False)
# ---- extract result
ext = {'generated_at': gaps['generated_at'], 'order': 'CoS 2026-10-02 07:28 PT + Watchdog GO; collect+stage only, NO PUBLISH, NO IR', 'repo': 'endomorphosis/ipfs_germany_laws',
       'old_tip': chk['live_tip'], 'staging_path': str(S), 'uploaded': False, 'never_thin_PASS': chk['PASS'],
       'federal_before': chk['federal_before'], 'federal_after': chk['federal_after'],
       'total_after': {'laws': chk['laws']['new_rows'], 'articles': chk['articles']['new_rows']},
       'per_land': {f'DE-{l}': {'laws': per[f'DE-{l}']['laws'], 'articles': per[f'DE-{l}']['articles'], 'laws_gesetze': bper[f'DE-{l}'].get('laws_statute', 0), 'laws_verordnungen': bper[f'DE-{l}'].get('laws_regulation', 0),
                                'articles_gesetze': bper[f'DE-{l}'].get('articles_statute', 0), 'articles_verordnungen': bper[f'DE-{l}'].get('articles_regulation', 0),
                                'empty_article_text_rows': bper[f'DE-{l}'].get('article_rows_empty_text', 0), 'empty_non_structural': bper[f'DE-{l}'].get('article_rows_empty_text_non_structural', 0),
                                'law_body_under_200_chars': bper[f'DE-{l}'].get('law_text_body_under_200_chars', 0), 'zero_article_laws': bper[f'DE-{l}'].get('zero_article_laws', 0)} for l in lands_c},
       'blocked': {k: v['status'] for k, v in gaps['lands'].items() if v['status'] != 'COLLECTED'}, 'collector': col, 'supplement': sup, 'build_report': brep}
json.dump(ext, open(T / 'germany_subnational_extract_result.json', 'w'), indent=1, ensure_ascii=False)
# ---- README
fed = (B / 'de_tip' / 'README.md').read_text()
nl = chk['laws']['new_rows']; na = chk['articles']['new_rows']
fed = fed.replace('pretty_name: German Federal Law Corpus (Gesetze im Internet)', 'pretty_name: German Federal and State Law Corpus (Bundesrecht + Landesrecht)')
fed = fed.replace('- bundesrecht\n', '- bundesrecht\n- landesrecht\n').replace('size_categories:\n- 1K<n<10K', 'size_categories:\n- 10K<n<100K' if nl >= 10000 else 'size_categories:\n- 1K<n<10K')
fed = fed.replace('| Laws / instruments | 6127 |', f'| Laws / instruments | {nl} (federal 6127 + Landesrecht {nl - 6127}) |').replace('| Articles | 129983 |', f'| Articles | {na} (federal 129983 + Landesrecht {na - 129983}) |')
fed = fed.replace('| Jurisdiction | Germany |', '| Jurisdiction | Germany (`DE` federal; `DE-<Land>` Landesrecht) |')
t = ['| Land | jurisdiction | portal | laws | Gesetze | Verordnungen | articles | articles (Gesetze / VO) |', '| --- | --- | --- | ---: | ---: | ---: | ---: | --- |']
for l in lands_c:
    q = bper[f'DE-{l}']; t.append(f"| {NAMES[l]} | DE-{l} | {PORTAL[l]} | {per[f'DE-{l}']['laws']} | {q.get('laws_statute', 0)} | {q.get('laws_regulation', 0)} | {per[f'DE-{l}']['articles']} | {q.get('articles_statute', 0)} / {q.get('articles_regulation', 0)} |")
bl = ['| Land | status | reason / evidence |', '| --- | --- | --- |']
for k, v in gaps['lands'].items():
    if v['status'] != 'COLLECTED': bl.append(f"| {v['name']} ({k}) | {v['status']} | {v.get('reason', '')[:260]} |")
lic = '\n'.join(f'- **{NAMES[l]} (DE-{l})**: {LIC[l]}' for l in NAMES)
add = f"""
## Landesrecht (state law) append — staged {time.strftime('%Y-%m-%d')} (not yet published)

Federal rows (`jurisdiction='DE'`, gesetze-im-internet.de) are unchanged and come first; state-law rows are appended with
`jurisdiction='DE-<Land>'`, ids `de-<land>-<portal id>` (articles `<law id>:§ N`, `:header`, `:gl:<Gliederung>`, `:Eingangsformel` …),
`metadata_json.document_type` = `statute` (Gesetz) or `regulation` (Verordnung). Only in-force consolidated Gesetze and Rechtsverordnungen
from official Land portals; no third-party aggregators.

{chr(10).join(t)}

Not collected (see `PACK_META.json` and the gap list):

{chr(10).join(bl)}

## Known limitations

- Coverage is 4 of 16 Länder (BB, HB, NW, SN). BW: robots.txt disallows generic crawlers; BY: 503 bot-challenge; NI: § 44b(3) UrhG TDM reservation in the
  NI-VORIS terms; BE, HH, HE, MV, RP, SL, ST, SH, TH: juris-hosted portals refused TLS connections from the collector (BLOCKED_SOURCE).
- Portal texts are non-official consolidated reading versions (nichtamtliche Lesefassungen); only the promulgated gazette texts (GV. NRW., SächsGVBl., Brem.GBl., GVBl. Bbg) are authoritative.
- Scope: Gesetze + Rechtsverordnungen in force on the collection date. Verwaltungsvorschriften, Bekanntmachungen, Richtlinien, Staatsverträge (BB), Satzungen,
  and pure amending/repealing instruments are excluded. DE-HB includes Ortsgesetze of the Stadtgemeinde Bremen as filed by the portal.
- Article rows follow the federal layout, incl. structural Gliederung rows (`:gl:`) with empty text; footnotes are dropped from article text.
  Sentence numbers (REVOSax superscripts) are removed. Duplicate norm labels within one law get `#2`, `#3` suffixes.
- `eli` is null (as for federal rows); `json_path` points to the collector's raw HTML snapshot path; `law_status`='current' for all appended rows.
- Dates: `date`/`date_issued` = Ausfertigungsdatum where the portal shows it.

### Licence terms per Land

General: Gesetze and Verordnungen are amtliche Werke and **public domain (gemeinfrei) under § 5 Abs. 1 UrhG**. The portals' consolidated databases may
still be protected as databases (§ 87a ff. UrhG, sui generis right: extraction/re-use of substantial parts), and portal terms of use may add conditions.

{lic}
"""
(S / 'README.md').write_text(fed.rstrip() + '\n' + add)
m = (S / 'MANIFEST.md').read_text()
m += f"""
## Landesrecht append (staged {time.strftime('%Y-%m-%dT%H:%M:%S%z')}, uploaded: false)
base_tip: {chk['live_tip']}
laws_rows_after: {nl}
articles_rows_after: {na}
appended_jurisdictions: {', '.join('DE-' + l for l in lands_c)}
laws_sha256_staged: {chk['laws_sha256_staged']}
articles_sha256_staged: {chk['articles_sha256_staged']}
collector: scrapers/de_collect.py, scrapers/de_build.py
never_thin_precheck: {'PASS' if chk['PASS'] else 'FAIL'}
"""
(S / 'MANIFEST.md').write_text(m)
print('report written', T)
