#!/usr/bin/env python3
"""KH: ECCC chamber judges (Supreme Court Chamber, Trial Chamber, Pre-Trial Chamber) from the official
eccc.gov.kh/en/organisation/chambers page (Next.js page data, English locale). Public names/titles only.
Appends new judge_ids to data/kh/kh_judges.jsonl."""
import re, json, datetime, os, urllib.request, unicodedata
URL = 'https://www.eccc.gov.kh/en/organisation/chambers'
UA = 'WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)'
OUT = '/workspace/world_courts/data/kh/kh_judges.jsonl'
COURT = 'osm:node/1854006853'
CH = {'SUPREME_COURT_CHAMBER_JUDGES': 'Supreme Court Chamber', 'TRIAL_CHAMBER_JUDGES': 'Trial Chamber',
      'PRE_TRIAL_CHAMBER_JUDGES': 'Pre-Trial Chamber'}
s = urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': UA}), timeout=40).read().decode('utf-8').replace('\\"', '"')
pat = re.compile(r'"name":"([^"]+)","position":(null|"[^"]*"),"yearsActive":(null|"[^"]*"),"description":(?:null|"(?:[^"\\]|\\.)*"),"category":"([A-Z_]+)","isReserve":(true|false),"createdAt":"[^"]*","updatedAt":"[^"]*","publishedAt":"[^"]*","locale":"en"')
def slug(x):
    x = unicodedata.normalize('NFKD', x).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', x).strip('-')
existing = {json.loads(l)['judge_id'] for l in open(OUT) if l.strip()} if os.path.exists(OUT) else set()
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
out, seen = [], set()
for m in pat.finditer(s):
    name, pos, yrs, cat, res = m.groups()
    if cat not in CH: continue
    name = re.sub(r'\s+', ' ', name).strip(); pos = None if pos == 'null' else pos.strip('"')
    yrs = None if yrs == 'null' else yrs.strip('"').strip()
    reserve = res == 'true'
    jid = f"kh-eccc-{slug(CH[cat])}-{'reserve-' if reserve else ''}{slug(name)}"
    if jid in seen or jid in existing: continue
    seen.add(jid)
    if reserve: title = f"Reserve Judge, {CH[cat]}, ECCC"
    elif pos == 'President': title = f"President of the {CH[cat]}, ECCC"
    else: title = f"Judge, {CH[cat]}, ECCC"
    a, _, b = (yrs or '').partition('-')
    cur = b.strip().lower() == 'present'
    out.append({'judge_id': jid, 'court_id': COURT, 'name': name, 'title': title,
        'position_type': 'president' if pos == 'President' and not reserve else ('reserve' if reserve else 'judge'),
        'term_start': a.strip() if a.strip().isdigit() else None,
        'term_end': b.strip() if b.strip().isdigit() else None,
        'status': 'listed_current' if cur else 'former', 'chamber': CH[cat], 'jurisdiction': 'KH',
        'roster_url': URL, 'source_url': URL, 'source_kind': 'official',
        'site_policy': 'robots_allowed|eccc.gov.kh robots.txt: User-agent * with no disallow rules|official ECCC website, no restrictive terms found',
        'retrieved_at': now, 'needs_review': True,
        'extraction': f'ECCC chambers page, years active "{yrs}" (ECCC now in residual-functions phase; "present" as stated by site)',
        'license': 'official public court information (facts)'})
with open(OUT, 'a') as f:
    for o in out: f.write(json.dumps(o, ensure_ascii=False) + '\n')
print('new', len(out))
