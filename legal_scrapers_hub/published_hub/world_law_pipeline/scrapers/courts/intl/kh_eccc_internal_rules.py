#!/usr/bin/env python3
"""KH: ECCC Internal Rules (Rev. 9, 16 Jan 2015) -> data/kh/kh_rules.jsonl.
Source: official ECCC PDF (eccc.gov.kh). Polite single fetch, honest UA. Appends only new rule_ids."""
import json, re, hashlib, subprocess, datetime, os, sys, urllib.request
ROOT = '/workspace/world_courts'
URL = 'https://eccc.gov.kh/sites/default/files/legal-documents/Internal_Rules_Rev_9_Eng.pdf'
UA = 'WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)'
RAW = f'{ROOT}/rules/raw/kh/ir9.pdf'
OUT = f'{ROOT}/data/kh/kh_rules.jsonl'
os.makedirs(os.path.dirname(RAW), exist_ok=True)
if not os.path.exists(RAW):
    req = urllib.request.Request(URL, headers={'User-Agent': UA})
    open(RAW, 'wb').write(urllib.request.urlopen(req, timeout=60).read())
pdf = open(RAW, 'rb').read(); sha = hashlib.sha256(pdf).hexdigest()
txt = subprocess.run(['pdftotext', RAW, '-'], capture_output=True, text=True).stdout
lines = txt.split('\n')
# body starts at second 'Rule 1. Entry into Force'
starts = [i for i, l in enumerate(lines) if l.strip().startswith('Rule 1. Entry into Force')]
body = lines[starts[-1]:]
HEAD = re.compile(r'^Rule (\d+(?: (?:bis|ter|quater|quinquies|sexies))?)\.\s+(.+)$')
PART = re.compile(r'^([IVX]+)\s+[–-]\s+(.+)$')
NOISE = re.compile(r'^(\d{1,3}|Internal Rules \(Rev\.\s*9\).*|.*as revised on 16 January 2015\s*)$')
rules, cur, part = [], None, 'I – PROVISIONS RELATING TO THESE INTERNAL RULES (“IRs”)'
for l in body:
    s = l.strip().replace('\f', '')
    if s == 'GLOSSARY':
        break
    if NOISE.match(s) and not HEAD.match(s):
        continue
    m = HEAD.match(s)
    if m and m.group(1) in {r['num'] for r in rules}:
        m = None  # wrapped cross-reference, not a heading
    if m:
        cur = {'num': m.group(1), 'title': m.group(2).strip(), 'part': part, 'text': []}; rules.append(cur); continue
    pm = PART.match(s)
    if pm and s.upper() == s:
        part = s; continue
    if cur is not None:
        cur['text'].append(s)
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
existing = set()
if os.path.exists(OUT):
    existing = {json.loads(l)['rule_id'] for l in open(OUT) if l.strip()}
seen, out = set(), []
for r in rules:
    rid = 'kh-eccc-ir9:r' + r['num'].replace(' ', '-')
    if rid in seen or rid in existing:
        continue
    seen.add(rid)
    text = re.sub(r'\n{3,}', '\n\n', '\n'.join(r['text'])).strip()
    out.append({'rule_id': rid, 'rule_set_id': 'kh-eccc-ir9', 'court_id': 'osm:node/1854006853', 'jurisdiction': 'KH',
        'rule_set': 'Extraordinary Chambers in the Courts of Cambodia Internal Rules (Rev. 9), as revised on 16 January 2015',
        'rule_number': 'Rule ' + r['num'], 'title': r['title'], 'part': r['part'], 'text': text or None,
        'effective_date': '2015-01-16', 'pdf_path': 'rules/raw/kh/ir9.pdf', 'pdf_sha256': sha, 'source_sha256': sha,
        'source_url': URL, 'site_policy': 'robots_allowed|eccc.gov.kh robots.txt: User-agent * with no disallow rules|official ECCC publication, no restrictive terms found',
        'retrieved_at': now, 'license': 'official court publication (ECCC); no licence stated', 'language': 'en',
        'source_kind': 'official', 'needs_review': False,
        'version_note': 'ECCC (hybrid Cambodian/UN court, now residual functions) procedural rules; English official version, Khmer/French equally authentic'})
with open(OUT, 'a') as f:
    for o in out: f.write(json.dumps(o, ensure_ascii=False) + '\n')
print('parsed', len(rules), 'new', len(out))
