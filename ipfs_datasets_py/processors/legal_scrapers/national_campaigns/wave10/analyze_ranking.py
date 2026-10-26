#!/usr/bin/env python3
"""Wave 10 step 1b: classify ranked repos; find UN members with no repo;
list thinnest national repos outside the waves 6-9 scope."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, re

WAVE10 = os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/wave10")
rs = json.load(open(os.path.join(WAVE10, "stats", "ranking.json")))
un = json.load(open(os.path.join(WAVE10, "stats", "un_members.json")))

# repo -> (UN country name or None for non-UN, iso2 or '')
MAP = {
 'afghanistan':'Afghanistan','albania':'Albania','algeria':'Algeria','andorra':'Andorra','angola':'Angola',
 'antigua_barbuda':'Antigua and Barbuda','argentina':'Argentina','armenia':'Armenia','australia':'Australia',
 'austria':'Austria','azerbaijan':'Azerbaijan','bahamas':'Bahamas','bahrain':'Bahrain','bangladesh':'Bangladesh',
 'barbados':'Barbados','belarus':'Belarus','belgium':'Belgium','belize':'Belize','benin':'Benin','bhutan':'Bhutan',
 'bolivia':'Bolivia','bosnia':'Bosnia and Herzegovina','botswana':'Botswana','brazil':'Brazil','brunei':'Brunei',
 'bulgaria':'Bulgaria','burkinafaso':'Burkina Faso','burundi':'Burundi','caboverde':'Cabo Verde','cambodia':'Cambodia',
 'cameroon':'Cameroon','canada':'Canada','car':'Central African Republic','chad':'Chad','chile':'Chile','china':'China',
 'colombia':'Colombia','comoros':'Comoros','congobrazzaville':'Congo','costarica':'Costa Rica','cotedivoire':"Côte d'Ivoire",
 'croatia':'Croatia','cuba':'Cuba','cyprus':'Cyprus','czechia':'Czechia','drc':'Democratic Republic of the Congo',
 'denmark':'Denmark','djibouti':'Djibouti','dominica':'Dominica','dominican_republic':'Dominican Republic',
 'dominicanrepublic':'Dominican Republic','ecuador':'Ecuador','egypt':'Egypt','el_salvador':'El Salvador',
 'elsalvador':'El Salvador','equatorialguinea':'Equatorial Guinea','eritrea':'Eritrea','estonia':'Estonia',
 'eswatini':'Eswatini','ethiopia':'Ethiopia','fiji':'Fiji','finland':'Finland','france':'France','fsm':'Micronesia',
 'gabon':'Gabon','gambia':'Gambia','georgia':'Georgia','germany':'Germany','ghana':'Ghana','greece':'Greece',
 'grenada':'Grenada','guatemala':'Guatemala','guinea':'Guinea','guineabissau':'Guinea-Bissau','guyana':'Guyana',
 'haiti':'Haiti','honduras':'Honduras','hungary':'Hungary','iceland':'Iceland','india':'India','indonesia':'Indonesia',
 'iran':'Iran','iraq':'Iraq','ireland':'Ireland','israel':'Israel','italy':'Italy','jamaica':'Jamaica','japan':'Japan',
 'jordan':'Jordan','kazakhstan':'Kazakhstan','kenya':'Kenya','kiribati':'Kiribati','korea':'South Korea',
 'kosovo':'Kosovo (non-UN)','kuwait':'Kuwait','kyrgyzstan':'Kyrgyzstan','laos':'Laos','latvia':'Latvia',
 'lebanon':'Lebanon','lesotho':'Lesotho','liberia':'Liberia','libya':'Libya','liechtenstein':'Liechtenstein',
 'lithuania':'Lithuania','luxembourg':'Luxembourg','madagascar':'Madagascar','malawi':'Malawi','malaysia':'Malaysia',
 'maldives':'Maldives','mali':'Mali','malta':'Malta','marshallislands':'Marshall Islands','mauritania':'Mauritania',
 'mauritius':'Mauritius','mexico':'Mexico','moldova':'Moldova','monaco':'Monaco','mongolia':'Mongolia',
 'montenegro':'Montenegro','morocco':'Morocco','mozambique':'Mozambique','myanmar':'Myanmar','namibia':'Namibia',
 'nauru':'Nauru','nepal':'Nepal','netherlands':'Netherlands','newzealand':'New Zealand','nicaragua':'Nicaragua',
 'niger':'Niger','nigeria':'Nigeria','niue':'Niue','north_korea':'North Korea','northkorea':'North Korea',
 'northmacedonia':'North Macedonia','norway':'Norway','oman':'Oman','pakistan':'Pakistan','palau':'Palau',
 'panama':'Panama','papua_new_guinea':'Papua New Guinea','papuanewguinea':'Papua New Guinea','paraguay':'Paraguay',
 'peru':'Peru','philippines':'Philippines','poland':'Poland','portugal':'Portugal','qatar':'Qatar','romania':'Romania',
 'russia':'Russia','rwanda':'Rwanda','saint_kitts_nevis':'Saint Kitts and Nevis','saint_lucia':'Saint Lucia',
 'saint_vincent_grenadines':'Saint Vincent and the Grenadines','samoa':'Samoa','san_marino':'San Marino',
 'sanmarino':'San Marino','saotome':'Sao Tome and Principe','saudiarabia':'Saudi Arabia','senegal':'Senegal',
 'serbia':'Serbia','seychelles':'Seychelles','sierraleone':'Sierra Leone','singapore':'Singapore','slovakia':'Slovakia',
 'slovenia':'Slovenia','solomonislands':'Solomon Islands','somalia':'Somalia','southafrica':'South Africa',
 'southsudan':'South Sudan','spain':'Spain','srilanka':'Sri Lanka','sudan':'Sudan','suriname':'Suriname',
 'sweden':'Sweden','switzerland':'Switzerland','syria':'Syria','tajikistan':'Tajikistan','tanzania':'Tanzania',
 'thailand':'Thailand','timorleste':'Timor-Leste','togo':'Togo','tonga':'Tonga','trinidad_and_tobago':'Trinidad and Tobago',
 'trinidad':'Trinidad and Tobago','tunisia':'Tunisia','turkey':'Turkey','turkmenistan':'Turkmenistan','tuvalu':'Tuvalu',
 'uae':'United Arab Emirates','uk':'United Kingdom','uganda':'Uganda','ukraine':'Ukraine','uruguay':'Uruguay',
 'uzbekistan':'Uzbekistan','vanuatu':'Vanuatu','venezuela':'Venezuela','vietnam':'Vietnam','yemen':'Yemen',
 'zambia':'Zambia','zimbabwe':'Zimbabwe',
 # non-UN territories / other
 'anguilla':'Anguilla (UK OT)','aruba':'Aruba (NL)','bermuda':'Bermuda (UK OT)','british_virgin_islands':'British Virgin Islands (UK OT)',
 'cayman':'Cayman Islands (UK OT)','cookislands':'Cook Islands (NZ assoc.)','curacao':'Curaçao (NL)','eu':'European Union',
 'guam':'Guam (US)','hongkong':'Hong Kong (CN)','montserrat':'Montserrat (UK OT)','new_caledonia':'New Caledonia (FR)',
 'palestine':'Palestine (UN observer)','pitcairn':'Pitcairn (UK OT)','puerto_rico':'Puerto Rico (US)',
 'sint_maarten':'Sint Maarten (NL)','taiwan':'Taiwan','turks_caicos':'Turks and Caicos (UK OT)','vatican':'Vatican (UN observer)',
 'uk_local_acts':'United Kingdom (local acts)',
}
WAVES69 = {'ipfs_somalia_laws','ipfs_equatorialguinea_laws','ipfs_niue_laws','ipfs_southsudan_laws',
           'ipfs_suriname_laws','ipfs_vanuatu_laws','ipfs_burundi_laws','ipfs_afghanistan_laws',
           'ipfs_gambia_laws','ipfs_eritrea_laws','ipfs_sudan_laws','ipfs_lesotho_laws',
           'ipfs_papua_new_guinea_laws'}
EXCLUDE_ALWAYS = {'ipfs_north_korea_laws','ipfs_northkorea_laws','ipfs_kosovo_laws'}

def classify(rec):
    repo = rec['repo']
    if '_municipal_' in repo: return 'municipal'
    if repo == 'ipfs_embeddings_test': return 'not-laws'
    slug = repo[len('ipfs_'):-len('_laws')] if repo.endswith('_laws') else repo
    if repo == 'ipfs_uk_local_acts': return 'subnational'
    return 'national' if slug in MAP else 'national-unmapped'

out = {'national': [], 'municipal': [], 'other': [], 'errors': []}
for rec in rs:
    kind = classify(rec)
    slug = rec['repo'][len('ipfs_'):-len('_laws')] if rec['repo'].endswith('_laws') else rec['repo']
    rec['country'] = MAP.get(slug, '?')
    rec['kind'] = kind
    if rec.get('rows') is None: out['errors'].append(rec)
    elif kind == 'national': out['national'].append(rec)
    elif kind == 'municipal': out['municipal'].append(rec)
    else: out['other'].append(rec)

covered = {r['country'] for r in out['national']}
no_repo = [c for c in un if c not in covered]
out['national'].sort(key=lambda r: r['rows'])
thin = [r for r in out['national'] if r['repo'] not in WAVES69 and r['repo'] not in EXCLUDE_ALWAYS]
res = {'counts': {k: len(v) for k, v in out.items()},
       'un_members_without_repo': no_repo,
       'thinnest_outside_waves69': [{'repo': r['repo'], 'country': r['country'], 'rows': r['rows'],
                                     'layout': r['layout']} for r in thin[:30]],
       'all_national_sorted': [{'repo': r['repo'], 'country': r['country'], 'rows': r['rows'],
                                'layout': r['layout'], 'rows_per_file': r.get('rows_per_file')}
                               for r in out['national']],
       'municipal': [{'repo': r['repo'], 'rows': r['rows'], 'layout': r['layout']} for r in sorted(out['municipal'], key=lambda r: r['rows'])],
       'other': [{'repo': r['repo'], 'rows': r['rows'], 'layout': r['layout'], 'kind': r['kind']} for r in out['other']],
       'errors': [{'repo': r['repo'], 'error': r.get('error')} for r in out['errors']]}
json.dump(res, open(os.path.join(WAVE10, 'stats', 'ranking_analysis.json'), 'w'), indent=1)
print(json.dumps(res['counts'], indent=1))
print('UN members without repo:', no_repo)
print('thinnest outside waves 6-9 scope:')
for t in res['thinnest_outside_waves69'][:20]:
    print(f"  {t['rows']:>7}  {t['repo']}  ({t['country']})  {t['layout']}")
