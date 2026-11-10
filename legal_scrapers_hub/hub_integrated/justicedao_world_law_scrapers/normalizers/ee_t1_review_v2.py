#!/usr/bin/env python3
"""EE municipal T1 review v2 (post-fix + strip pass, as of 2024-11-01). Offline, read-only on shards; writes review/ee_t1_review_strip_<ts>.{json,md}
and appends review/index.json. Strip hand check: placeholders are verified by re-decoding the blob from the backup (pre-fix) source text.
No hub pushes. Streams shards one record at a time under the ee_t1_fix memory guard.
Usage: nice -n 19 /workspace/venv/bin/python -u /workspace/scripts/ee_t1_review_v2.py [--seed 20241101] [--backup DIR]
Contents: totals, status, canonical / non-canonical, repealed, articles (canonical non-repealed only), by LG, EHAK coverage before/after + unmapped LGs,
version groups (base key LG+type+number and refined key), ambiguous groups + rule, acts > 1 MB, empties, duplicates (id; LG+type+number+version),
article-id uniqueness, shard sha256 + caps, and a 20-item stratified hand check (6 repealed stubs, 6 versioned-group members, 6 EHAK successor-mapped,
2 others) checked field-by-field against the source text and the pre-fix record (backup shards = original RT XML parse)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, random, hashlib, time, argparse, collections, glob, csv, base64
sys.path.insert(0, '/workspace/scripts')
import ee_t1_fix as F
ap = argparse.ArgumentParser(); ap.add_argument('--seed', type=int, default=20241101); ap.add_argument('--backup', default=None)
A = ap.parse_args(); ROOT = F.ROOT; SH = F.SH; RD = f'{ROOT}/review'; D = F.AS_OF; PREV_D = F.SOURCE_GENERATED; ARTS_PREV = 2072
PH = re.compile(r'\[attachment: ([^\n]*?), ([a-z]+/[\w.+-]+|unknown \(undecodable base64\)), (\d+|\d+ base64 chars), ([0-9a-f]{64}|base64-text sha256 [0-9a-f]{64})\]')
LAW_COLS = ['id', 'title', 'text', 'source_url', 'source_type', 'jurisdiction', 'country', 'language', 'eli', 'date', 'date_issued', 'retrieved_at',
            'license', 'law_status', 'identifier', 'official_identifier', 'article_count', 'json_path', 'metadata_json']
ART_COLS = ['law_id', 'id', 'title', 'text', 'source_url', 'document_number', 'article_number', 'record_type', 'metadata_json']
BK = A.backup or F.latest_backup()
guard = F.Guard(); ts = time.strftime('%Y%m%dT%H%M%S'); man = json.load(open(F.MAN)); msha = F.sha_file(F.MAN)
def tsha(t): return hashlib.sha256((t or '').encode('utf-8')).hexdigest()
# ---------------- pass 1 over fixed shards ----------------
sha_bad = [n for n, s in man['shards'].items() if F.sha_file(f'{SH}/{n}') != s['sha256']]
caps_bad = [n for n, s in man['shards'].items() if s['n_laws'] > F.SHARD_N or s['unpacked_bytes'] > F.SHARD_MAX]
C = []; art_ids = collections.Counter(); n_art = 0; empty = []; cols_bad = []
for _, r in F.stream(SH, guard):
    law = r['law']; md = json.loads(law['metadata_json']); t = law['text'] or ''
    if set(law) != set(LAW_COLS): cols_bad.append(law['id'])
    for a in r['articles']:
        art_ids[a['id']] += 1; n_art += 1
        if set(a) != set(ART_COLS): cols_bad.append(a['id'])
    if not t.strip(): empty.append(law['id'])
    C.append(dict(id=law['id'], st=law['law_status'], vt_eff=md.get('valid_to_effective'), lg=md.get('lg_name'), issuer=md.get('issuer'), dt=md.get('doc_type'), no=md.get('act_no'), ver=md.get('version'),
                  vf=md.get('valid_from'), vt=md.get('valid_to_effective'), adopted=md.get('adopted'), can=md['is_canonical'], vof=md.get('version_of'), feeds=md['feeds_articles'],
                  gk=md['version_group_key'], bk=md['version_group_base_key'], gsize=md['version_group_size'], basis=md['canonical_basis'], amb=md['canonical_ambiguous'],
                  inf=md['in_force_as_of'], vt_src=md.get('valid_to'), never=bool(md.get('never_in_force')), sup=md.get('superseded_by_repeal_stub'), stub=md['is_repeal_stub'], before=md['status_before_fix'], ehak=md.get('ehak_code'), em=md['ehak_match'], succ=md.get('ehak_successor'),
                  succ_name=md.get('ehak_successor_name'), unmapped_reason=md.get('ehak_unmapped_reason'), tb=md['text_bytes'], b64=md.get('text_base64_run_chars', 0), n_art=len(r['articles']),
                  parsed_n=md['articles_parsed_n'], pub=md.get('published'), vd=md.get('version_date'), mvd=md.get('meta_version_date'), ab64=md.get('articles_base64_chars', 0), rep_ok=md.get('repeal_checks_ok'), rep_in=md.get('repeal_in_effect_as_of'), title=(law['title'] or '')[:120],
                  att_n=md.get('attachments_stripped_n', 0), att_art=sum(1 for e in md.get('attachments_stripped', []) if e['location'] != 'text'), tnote=bool(md.get('title_note')),
                  tb0=md.get('text_bytes_before_strip', 0), resid=max([F.residual_b64(z) for z in F.iter_str([law, md, r['articles']])] or [0]), asof=md.get('as_of_date'),
                  att=[(e['name_source'], e['decode_ok'], e['mime']) for e in md.get('attachments_stripped', [])],
                  suffixed=sum(1 for a in r['articles'] if '"id_original"' in a['metadata_json'])))
    del r, law, md, t
N = len(C); by = collections.defaultdict(list)
for c in C: by[c['gk']].append(c)
base = collections.defaultdict(list)
for c in C: base[c['bk']].append(c)
def dups(key):
    k = collections.Counter(key(c) for c in C); return dict(groups=sum(1 for v in k.values() if v > 1), extra_entries=sum(v - 1 for v in k.values() if v > 1),
                                                           examples=[[list(x) if isinstance(x, tuple) else x, v] for x, v in k.most_common(6) if v > 1])
status = collections.Counter(c['st'] for c in C)
lg = collections.OrderedDict()
for c in sorted(C, key=lambda c: c['lg'] or ''):
    e = lg.setdefault(c['lg'], dict(ehak=c['ehak'], ehak_match=c['em'], ehak_successor=c['succ'], successor_name=c['succ_name'], acts=0, repealed=0, canonical=0, feeds=0, articles=0))
    e['acts'] += 1; e['repealed'] += c['st'] == 'repealed'; e['canonical'] += c['can']; e['feeds'] += c['feeds']; e['articles'] += c['n_art']
ehak_before = dict(acts_with_ehak=sum(1 for c in C if c['ehak']), acts_null=sum(1 for c in C if not c['ehak']), lgs=len(lg), lgs_with_ehak=sum(1 for v in lg.values() if v['ehak']))
ehak_after = dict(acts_direct=sum(1 for c in C if c['em'] == 'direct'), acts_successor_mapped=sum(1 for c in C if c['em'] == 'successor'), acts_still_null=sum(1 for c in C if c['em'] == 'unmapped'),
                  lgs_direct=sum(1 for v in lg.values() if v['ehak_match'] == 'direct'), lgs_successor_mapped=sum(1 for v in lg.values() if v['ehak_match'] == 'successor'),
                  lgs_still_null=sum(1 for v in lg.values() if v['ehak_match'] == 'unmapped'))
mixed_lg = [k for k in lg if len({c['em'] for c in C if c['lg'] == k}) > 1]
unmapped = collections.Counter(c['lg'] for c in C if c['em'] == 'unmapped')
succ_map = {k: dict(successor=v['ehak_successor'], name=v['successor_name'], acts=v['acts']) for k, v in lg.items() if v['ehak_match'] == 'successor'}
multi = {k: v for k, v in by.items() if len(v) > 1}
vg = dict(base_key='LG + doc type + act number', refined_key='LG + doc type + act number + issuer + adoption date',
          base_groups_multi=sum(1 for v in base.values() if len(v) > 1), base_extra=sum(len(v) - 1 for v in base.values() if len(v) > 1),
          base_groups_split_into_distinct_acts=sum(1 for v in base.values() if len({c['gk'] for c in v}) > 1),
          groups_total=len(by), groups_multi=len(multi), versions_in_multi=sum(len(v) for v in multi.values()), non_canonical=sum(1 for c in C if not c['can']),
          size_distribution=dict(sorted(collections.Counter(len(v) for v in by.values()).items())),
          canonical_basis=dict(collections.Counter(c['basis'] for c in C if c['can'])),
          groups_whose_canonical_is_repealed=sum(1 for v in by.values() if any(c['can'] and c['st'] == 'repealed' for c in v)),
          multi_groups_whose_canonical_is_repealed=sum(1 for v in multi.values() if any(c['can'] and c['st'] == 'repealed' for c in v)),
          non_canonical_still_labelled_current=sum(1 for c in C if not c['can'] and c['st'] == 'current'),
          canonical_not_in_force_on_as_of=sum(1 for c in C if c['can'] and not c['inf']),
          canonical_feeding_but_not_in_force=sum(1 for c in C if c['feeds'] and not c['inf']))
# comparison with the previous fix pass (dump date 2026-10-04, source valid_to, no supersession) -> article delta explanation
prev_rows = [dict(c, vt=c['vt_src'], never=False) for c in C]
dec_prev, _, amb_prev = F.decide_versions(prev_rows, d=PREV_D)
feeds_prev = {c['id']: dec_prev[c['id']]['is_canonical'] and not c['stub'] for c in C}
arts_prev = sum(c['parsed_n'] for c in C if feeds_prev[c['id']])
gain = [c for c in C if c['feeds'] and not feeds_prev[c['id']]]; lose = [c for c in C if feeds_prev[c['id']] and not c['feeds']]
def why_gain(c):
    g = by[c['gk']]; pc = next(x for x in g if dec_prev[x['id']]['is_canonical'])
    if pc['stub']: return f"previous canonical {pc['id']} was a repeal stub in effect on {PREV_D} (repeal effective {pc['vf']}, after {D}); this version was in force on {D}"
    if pc['vf'] and pc['vf'] > D: return f"previous canonical {pc['id']} starts {pc['vf']} (after {D}); this version was in force on {D}"
    return f"previous canonical {pc['id']} ({pc['vf']}..{pc['vt_src'] or ''}); canonical rule on {D} selects this version"
def why_lose(c):
    g = by[c['gk']]; nc = next(x for x in g if x['can'])
    if c['vf'] and c['vf'] > D: return f"starts {c['vf']} (after {D}); canonical on {D} is {nc['id']}"
    return f"canonical on {D} is {nc['id']} ({nc['st']})"
delta = dict(articles_previous_fix_pass=ARTS_PREV, articles_previous_recomputed=arts_prev, articles_now=n_art, delta=n_art - ARTS_PREV, delta_pct=round(100 * (n_art - ARTS_PREV) / ARTS_PREV, 2),
             band=[round(ARTS_PREV * 0.9), int(ARTS_PREV * 1.1)], in_band=round(ARTS_PREV * 0.9) <= n_art <= int(ARTS_PREV * 1.1),
             feeding_acts_previous=sum(feeds_prev.values()), feeding_acts_now=sum(c['feeds'] for c in C),
             acts_gaining_feed=len(gain), articles_gained=sum(c['parsed_n'] for c in gain), acts_losing_feed=len(lose), articles_lost=sum(c['parsed_n'] for c in lose),
             gain_reasons=dict(collections.Counter(re.sub(r'EE-RT-\d+|\d{4}-\d{2}-\d{2}', '*', why_gain(c)) for c in gain)),
             lose_reasons=dict(collections.Counter(re.sub(r'EE-RT-\d+|\d{4}-\d{2}-\d{2}', '*', why_lose(c)) for c in lose)),
             gained=[dict(id=c['id'], lg=c['lg'], articles=c['parsed_n'], why=why_gain(c)) for c in sorted(gain, key=lambda c: -c['parsed_n'])],
             lost=[dict(id=c['id'], lg=c['lg'], articles=c['parsed_n'], why=why_lose(c)) for c in sorted(lose, key=lambda c: -c['parsed_n'])],
             ambiguous_groups_previous=len(amb_prev),
             explanation=(f'All of the change comes from moving the as-of date from {PREV_D} to {D}; article parsing, version grouping, and the canonical rule are unchanged. '
                          f'On {D}, versions that were later repealed or replaced (repeal stubs or newer versions in force from 2025 on) were still in force, so they become canonical and feed articles. '
                          f'Versions that only start after {D} stop feeding.'))
vg['comparison_with_previous_dump_date'] = dict(previous_date=PREV_D, groups_with_different_canonical=sum(1 for c in C if c['can'] and not dec_prev[c['id']]['is_canonical']),
                                                ambiguous_groups_previous=len(amb_prev))
sup_l = [dict(id=c['id'], lg=c['lg'], no=c['no'], status=c['st'], vf=c['vf'], vt_source=c['vt_src'], vt_effective=c['vt_eff'], superseded_by=c['sup'], never_in_force=c['never'], canonical=c['can']) for c in C if c['sup']]
att_c = collections.Counter(); 
for c in C:
    for ns, ok_, mime in c['att']: att_c[f'name_source:{ns}'] += 1; att_c[f'mime:{mime}'] += 1; att_c['decode_ok'] += bool(ok_)
strip = dict(man['fix']['strip'], acts_with_placeholders=sum(1 for c in C if c['att_n']), placeholders=sum(c['att_n'] for c in C), in_article_rows=sum(c['att_art'] for c in C),
             attachment_stats=dict(att_c), max_residual_base64_run=max(c['resid'] for c in C), acts_over_1mb_after=sum(1 for c in C if c['tb'] > F.MB1),
             max_text_bytes=max(c['tb'] for c in C), titles_with_note_left=sum(1 for c in C if F.TITLE_NOTE.match(c['title'] or '')), titles_cleaned=sum(c['tnote'] for c in C),
             records_without_as_of_date=sum(1 for c in C if c['asof'] != D))
b64 = dict(acts_with_base64_lines_left=sum(1 for c in C if c['b64'] > 0), base64_line_chars_left=sum(c['b64'] for c in C), base64_chars_in_article_rows_left=sum(c['ab64'] for c in C),
           max_residual_base64_run_any_field=max(c['resid'] for c in C), text_bytes_before_strip=sum(c['tb0'] for c in C), text_bytes_after_strip=sum(c['tb'] for c in C))
amb = [dict(group=k, size=len(v), basis=next(c['basis'] for c in v if c['can']), canonical=next(c['id'] for c in v if c['can']),
            members=[f"{c['id']} {c['st']} {c['vf']}..{c['vt'] or ''}{' STUB' if c['stub'] else ''}" for c in sorted(v, key=lambda c: c['vf'] or '')])
       for k, v in by.items() if any(c['amb'] for c in v)]
big = sorted([dict(id=c['id'], lg=c['lg'], title=c['title'][:80], text_bytes=c['tb'], base64_run_chars=c['b64'], articles_base64_chars=c['ab64'], status=c['st'], canonical=c['can'], feeds_articles=c['feeds'], articles=c['n_art'])
              for c in C if c['tb'] > F.MB1], key=lambda x: -x['text_bytes'])
totals = dict(acts=N, by_status=dict(status), repealed=status.get('repealed', 0), canonical=sum(c['can'] for c in C), non_canonical=sum(not c['can'] for c in C),
              canonical_non_repealed_feeding=sum(c['feeds'] for c in C), articles=n_art, articles_from_feeding_acts_only=sum(c['n_art'] for c in C if c['feeds']),
              articles_on_non_feeding_acts=sum(c['n_art'] for c in C if not c['feeds']), articles_before_fix=json.load(open(f'{BK}/manifest.json')).get('n_articles'), articles_previous_fix_pass=ARTS_PREV,
              superseded_by_repeal_stub=len(sup_l), never_in_force=sum(c['never'] for c in C), ambiguous_groups=len(amb),
              article_ids_unique=all(v == 1 for v in art_ids.values()), article_id_dups=sum(v - 1 for v in art_ids.values() if v > 1),
              acts_with_suffixed_article_ids=[c['id'] for c in C if c['suffixed']], suffixed_article_ids=sum(c['suffixed'] for c in C),
              empty_text=len(empty), lgs=len(lg), shards=len(man['shards']), shard_sha256_mismatch=sha_bad, shard_cap_violations=caps_bad, schema_violations=cols_bad[:20],
              status_before_fix_of_repealed=dict(collections.Counter(c['before'] for c in C if c['st'] == 'repealed')),
              repealed_in_effect_on_as_of=sum(1 for c in C if c['st'] == 'repealed' and c['rep_in']), repealed_source_anomalies=[c['id'] for c in C if c['st'] == 'repealed' and not c['rep_ok']])
dup = dict(id=dups(lambda c: c['id']), lg_type_number_version_field=dups(lambda c: (c['lg'], c['dt'], c['no'], c['ver'])),
           lg_type_number_valid_from=dups(lambda c: (c['lg'], c['dt'], c['no'], c['vf'])), refined_group_valid_from=dups(lambda c: (c['gk'], c['vf'])),
           lg_type_number_canonical_only=dups(lambda c: (c['lg'], c['dt'], c['no'], c['can'] or c['id'])), refined_group_canonical=dups(lambda c: (c['gk'], c['can'] or c['id'])))
# ---------------- 20-item stratified hand check ----------------
rnd = random.Random(A.seed); chosen = []
def pick(pool, n):
    pool = sorted([c for c in pool if c['id'] not in {x['id'] for x in chosen}], key=lambda c: c['id']); s = rnd.sample(pool, min(n, len(pool)))
    return s
strata = [('strip_placeholder', 4, [c for c in C if c['att_n']]),
          ('title_cleaned', 4, [c for c in C if c['tnote']]),
          ('repealed_stub', 4, [c for c in C if c['st'] == 'repealed']),
          ('versioned_group', 4, [c for c in C if c['gsize'] > 1 and c['st'] != 'repealed' and c['em'] != 'successor']),
          ('ehak_successor', 4, [c for c in C if c['em'] == 'successor' and c['st'] != 'repealed'])]
must = [x for x in ('EE-RT-405102024087', 'EE-RT-428082024023') if x in {c['id'] for c in C}]   # named in the strip orders: stub with trailing PDF; article-row blob
for i in must: chosen.append(dict(next(c for c in C if c['id'] == i), stratum='strip_placeholder', forced=True))
for name, n, pool in strata:
    for c in pick(pool, n - (len(must) if name == 'strip_placeholder' else 0)): chosen.append(dict(c, stratum=name))
ids = {c['id'] for c in chosen}
full = {}; src = {}
for _, r in F.stream(SH, guard):
    if r['law']['id'] in ids:
        law = r['law']; t = law['text'] or ''
        full[law['id']] = dict(law={k: v for k, v in law.items() if k != 'text'}, text=t, text_sha=tsha(t), text_head=t[:400], text_len=len(t),
                               articles=[dict(id=a['id'], md=a['metadata_json'], law_id=a['law_id'], text=a['text'], nonempty=bool((a['text'] or '').strip())) for a in r['articles']])
    del r
def verify_placeholders(fixed, source, ents):
    """independent of the strip code: the fixed text must be the source text with each blob region replaced by its placeholder; every blob region,
    re-read from the source, must be pure base64 whose decoded bytes have the placeholder's size and sha256. -> (fails, oks)"""
    fails = []; oks = []
    phs = list(PH.finditer(fixed))
    if len(phs) != len(ents): fails.append(f'{len(phs)} placeholders in text but {len(ents)} attachment entries'); return fails, oks
    parts = []; last = 0
    for m in phs: parts.append(fixed[last:m.start()]); last = m.end()
    parts.append(fixed[last:])
    pos = 0; pending = []
    for i, p in enumerate(parts):
        core = p.strip('\n') if i else p.rstrip('\n')
        if i and not core.strip() and i < len(parts) - 1: pending.append(ents[i - 1]); continue   # adjacent placeholders: one gap holds several blobs
        if i: pending.append(ents[i - 1])
        lo = pos + sum(e['base64_chars'] for e in pending)
        j = source.find(core, lo) if core else len(source) if i == len(parts) - 1 else lo
        if i == len(parts) - 1 and core and not source.endswith(core): fails.append('text after the last placeholder differs from the source tail'); break
        if i == len(parts) - 1 and core: j = len(source) - len(core)
        if j < 0: fails.append(f'text segment {i} not found in source: {core[:60]!r}'); break
        if i == 0:
            if not source.startswith(core): fails.append('text before the first placeholder differs from the source'); break
            pos = len(core); continue
        gap = re.sub(r'\s', '', source[pos:j])
        if re.search(r'[^A-Za-z0-9+/=]', gap): fails.append(f'blob region {i} contains non-base64 chars'); break
        off = 0
        for e in pending:
            chunk = gap[off:off + e['base64_chars']]; off += e['base64_chars']
            try: d = base64.b64decode(chunk, validate=True)
            except Exception: d = None
            if d is None or len(d) != e['bytes'] or hashlib.sha256(d).hexdigest() != e['sha256']: fails.append(f"attachment {e['index']} re-decode mismatch"); continue
            if e['mime'] == 'application/pdf' and not (d.startswith(b'%PDF') and b'%%EOF' in d[-64:]): fails.append(f"attachment {e['index']} not a complete PDF")
            oks.append(f"[{e['location']}] {e['name']} ({e['name_source']}): {e['bytes']:,} bytes re-decoded from the source blob, sha256 {e['sha256'][:12]}… matches")
        if off != len(gap): fails.append(f'blob region {i}: {len(gap) - off} base64 chars not accounted for')
        pending = []; pos = j + len(core)
    if not fails: oks.append('text outside the placeholders identical to source')
    return fails, oks
strip_res = {}
for _, r in F.stream(BK, guard):
    if r['law']['id'] in ids:
        law = r['law']; t = law['text'] or ''; f = full[law['id']]; fmd = json.loads(f['law']['metadata_json'])
        tents = [e for e in fmd.get('attachments_stripped', []) if e['location'] == 'text']
        res = dict(text=verify_placeholders(f['text'], t, tents) if tents else ((['text changed vs source'], []) if f['text'] != t else ([], ['text identical to source (no attachments)'])))
        sa = {a['id']: a['text'] for a in r['articles']}; af = []; ao = []
        for a in f['articles']:
            aents = json.loads(a['md']).get('attachments_stripped', [])
            st_ = sa.get(json.loads(a['md']).get('id_original', a['id']))
            if st_ is None: af.append(f"article {a['id']} not in source"); continue
            if aents: x, y = verify_placeholders(a['text'], st_, aents); af += x; ao += y
            elif a['text'] != st_: af.append(f"article {a['id']} text changed")
        res['articles'] = (af, ao)
        src[law['id']] = dict(law={k: v for k, v in law.items() if k != 'text'}, md=json.loads(law['metadata_json']), text_sha=tsha(t), text_head=t[:400], n_art=len(r['articles']), art_ids=[a['id'] for a in r['articles']],
                              b64_lines=F.b64_chars(t))
        strip_res[law['id']] = res
        del t, sa
    del r
E = F.EhakAP()
def indep_repeal(head):
    """independent tokenizer (no regex shared with ee_t1_fix): RT part, dates, digit runs, in order"""
    h = head.split('[attachment:')[0].split('\nJVBER')[0]; h = h.replace('Kehtetu', '', 1)
    x = h.strip().split(',')[0].strip()
    if '\n' not in x:   # run-together header: RT <part><published>[tz]<article+akt digits><effective>, read positionally (no shared regex)
        part = 'RT IV' if x.startswith('RT IV') else 'RT III' if x.startswith('RT III') else 'RT II' if x.startswith('RT II') else 'RT I' if x.startswith('RT I') else None
        rest = x[len(part or ''):].lstrip(); pub = rest[:10]; rest = rest[10:]
        if rest[:1] in '+-' and rest[3:4] == ':': rest = rest[6:]
        return part, [pub, rest[-10:]], [rest[:-10]]
    part = 'RT IV' if h.startswith('RT IV') or h.startswith('\nRT IV') else ('RT I' if 'RT I' in h[:6] else None)
    h2 = h.replace('RT IV', ' ').replace('RT I', ' ')
    toks = re.findall(r'\d{4}-\d{2}-\d{2}(?:[+-]\d{2}:\d{2})?|\d+', h2.split(',')[0])
    dates = [x[:10] for x in toks if re.fullmatch(r'\d{4}-\d{2}-\d{2}.*', x)]
    nums = [x for x in toks if x.isdigit()]
    return part, dates, nums
checks = []
for c in chosen:
    f = full[c['id']]; s = src[c['id']]; law = f['law']; md = json.loads(law['metadata_json']); flags = []; fails = []; ok = []
    if set(law) | {'text'} != set(LAW_COLS): fails.append('law columns != 19 hub cols')
    sr = strip_res[c['id']]; fails += sr['text'][0] + sr['articles'][0]; ok += sr['text'][1] + sr['articles'][1]
    if s['b64_lines'] and not md.get('attachments_stripped_n'): fails.append('source had base64 lines but no attachment was stripped')
    if F.residual_b64(f['text']) > 1000 or any(F.residual_b64(a['text']) > 1000 for a in f['articles']): fails.append('base64-looking run > 1k chars left')
    if md.get('repeal_trailing_text') and 'JVBER' in json.dumps(md): fails.append('blob fragment left in metadata')
    st_title = s['law']['title'] or ''
    if md.get('title_note'):
        if ' '.join(f"{law['title']} {md['title_note_ts']} {md['title_note']}".split()) != ' '.join(st_title.split()): fails.append('title + title_note != source title')
        elif re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}|Riigi Teataja seaduse', law['title']): fails.append('clean title still carries the note')
        else: ok.append(f"title cleaned: {law['title'][:60]!r}; note ({md['title_note_kind']}, {md['title_note_ts']}) moved to metadata title_note")
    elif law['title'] != st_title: fails.append('title changed without a title_note')
    if md.get('as_of_date') != D or md.get('status_ref_date') != D: fails.append('as_of_date/status_ref_date != 2024-11-01')
    if set(s['md']) - set(md): fails.append(f"source metadata keys dropped: {sorted(set(s['md']) - set(md))}")
    if law['article_count'] != len(f['articles']): fails.append('article_count != rows')
    if len({a['id'] for a in f['articles']}) != len(f['articles']): fails.append('article ids not unique')
    if any(a['law_id'] != c['id'] or not a['nonempty'] for a in f['articles']): fails.append('bad article row')
    if md['articles_parsed_n'] != s['n_art']: fails.append('articles_parsed_n != source article count')
    for k in ('valid_from', 'valid_to', 'adopted', 'act_no', 'issuer', 'lg_name', 'published', 'global_id'):
        if md.get(k) != s['md'].get(k): fails.append(f'{k} changed')
    if md['feeds_articles']:
        if len(f['articles']) != s['n_art']: fails.append('feeding act lost articles')
        else: ok.append(f"feeds {len(f['articles'])} articles (= source)")
    elif f['articles']: fails.append('non-feeding act has articles')
    else: ok.append(f"no articles (source had {s['n_art']}); feeds_articles=false")
    if re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} Riigi Teataja seaduse', law['title'] or ''): flags.append('title carries the RT "Kehtetu"-marked-version note from <aktinimi> (source-faithful, cosmetic)')
    if c['stratum'] == 'repealed_stub' or md['is_repeal_stub']:
        part, dates, nums = indep_repeal(f['text_head'])
        if law['law_status'] != 'repealed': fails.append('stub not repealed')
        if md['status_before_fix'] not in ('current', 'future_version'): flags.append(f"status_before_fix={md['status_before_fix']}")
        if part != md.get('repeal_rt_part'): fails.append(f"RT part {part} != {md.get('repeal_rt_part')}")
        if not dates or dates[0] != md.get('repeal_published'): fails.append(f"published {dates[:1]} != {md.get('repeal_published')}")
        if not dates or dates[-1] != md.get('repeal_effective'): fails.append(f"effective {dates[-1:]} != {md.get('repeal_effective')}")
        joined = ''.join(nums)
        if joined != md.get('repeal_rt_article', '') + md.get('repeal_rt_akt_id', ''): fails.append(f"article+akt digits {joined} != {md.get('repeal_rt_article')}+{md.get('repeal_rt_akt_id')}")
        else: ok.append(f"repeal {md['repeal_rt_ref']} akt {md['repeal_rt_akt_id']} effective {md['repeal_effective']} ({md['repeal_format']}) re-derived independently")
        if not md.get('repeal_checks_ok'): flags.append(f"source anomaly: akt id vs RT ref checks {md.get('repeal_checks')}")
        if md.get('repeal_effective') != md.get('valid_from'): flags.append(f"repeal_effective {md.get('repeal_effective')} != valid_from {md.get('valid_from')} (source)")
        if md.get('repeal_trailing_text'): ok.append(f"stub trailing attachment replaced by placeholder ({md['repeal_trailing_text']['chars']} chars)")
        if md.get('repeal_in_effect_as_of') != (md.get('repeal_effective', '9') <= D): fails.append('repeal_in_effect_as_of flag wrong')
        if not md.get('repeal_in_effect_as_of'): flags.append(f"repeal takes effect {md.get('repeal_effective')}, after the as-of date {D} (status repealed per order 1; repeal_in_effect_as_of=false)")
    # version checks (all items)
    g = by[c['gk']]; can = [x for x in g if x['can']]
    if len(can) != 1: fails.append(f'group has {len(can)} canonical')
    else:
        cn = can[0]
        if not md['is_canonical'] and md['version_of'] != cn['id']: fails.append('version_of != group canonical')
        exp_inf = [x for x in g if x['vf'] and x['vf'] <= D and (not x['vt'] or x['vt'] >= D) and not x['never']]
        if exp_inf and cn['id'] not in {x['id'] for x in exp_inf}: fails.append('canonical not among in-force versions')
        if len({(x['lg'], x['dt'], x['no'], (x['issuer'] or '').lower(), x['adopted']) for x in g}) != 1: fails.append('group members differ in LG/type/no/issuer/adopted')
        if len(g) > 1: ok.append(f"group of {len(g)}; canonical {cn['id']} ({cn['basis']}); this={'canonical' if md['is_canonical'] else 'version_of ' + str(md['version_of'])}; valid {md.get('valid_from')}..{md.get('valid_to') or ''}")
        if md['is_canonical'] and md['canonical_ambiguous']: flags.append(f"canonical by rule {md['canonical_basis']} (no unique in-force version on {D})")
    # as-of status (independent recompute from source valid_from/valid_to and the group's repeal stubs)
    if not md['is_repeal_stub']:
        vf, vt0 = s['md'].get('valid_from'), s['md'].get('valid_to'); vte = vt0
        stubs = [x for x in g if x['stub'] and x['vf'] and (x['pub'] or '') > (s['md'].get('published') or '') and x['vf'] >= (vf or '') and (not vt0 or vt0 >= x['vf'])]
        if stubs:
            sx = min(stubs, key=lambda x: x['vf']); vte = str(__import__('datetime').date.fromisoformat(sx['vf']) - __import__('datetime').timedelta(days=1))
            if md.get('superseded_by_repeal_stub') != sx['id']: fails.append('superseded_by_repeal_stub not recorded')
            else: ok.append(f"superseded by later repeal stub {sx['id']} (effective {sx['vf']}): valid_to_effective {vte}")
        elif md.get('superseded_by_repeal_stub'): fails.append('superseded flag without a later stub')
        exp = 'unknown' if not vf else 'historical_version' if (vte and vte < vf) else 'future_version' if vf > D else 'historical_version' if vte and vte < D else 'current'
        if law['law_status'] != exp: fails.append(f"law_status {law['law_status']} != expected {exp} as of {D}")
        else: ok.append(f"status {exp} as of {D} (valid {vf}..{vte or ''})")
    if law['law_status'] == 'current' and md.get('valid_from', '9') > D: fails.append('claims current but starts after the as-of date')
    if c['stratum'] == 'ehak_successor' or md['ehak_match'] == 'successor':
        if md.get('lg_name_original') != md.get('lg_name'): fails.append('lg_name_original != lg_name')
        stem = (md.get('lg_name') or '').rsplit(' ', 1)[0]
        if not (md.get('issuer') or '').startswith(stem): fails.append('issuer does not name the LG')
        rows = [r for r in E.rows if r['Value'][4:8] == md.get('ehak_abolished_code') and r['Value'][-2:] in ('01', '04')]
        if not rows or not rows[0]['ValidTo']: fails.append('abolished code not an ended municipality row in EHAK2017ap')
        if rows and not any(r['Label-et-EE'].split(' (')[0] == md.get('lg_name') or r['Label-et-EE'].startswith(stem) for r in rows): fails.append('abolished row label != LG name')
        e26 = E.e26.get(md.get('ehak_successor'))
        if not e26 or e26['name'] != md.get('ehak_successor_name'): fails.append('successor not in EHAK2026v1')
        chain_last = md['ehak_chain'][-1].get('to_code') if md.get('ehak_chain') else None
        if chain_last != md.get('ehak_successor'): fails.append('chain end != successor')
        succ_stem = (md.get('ehak_successor_name') or '').rsplit(' ', 1)[0]
        notes = ' '.join(l.get('note', '') for l in md.get('ehak_chain', []))
        if succ_stem and succ_stem in notes: ok.append(f"{md['lg_name']} [{md['ehak_abolished_code']}, ended {md['ehak_abolished_valid'].split('..')[1]}] -> {md['ehak_successor']} {md['ehak_successor_name']}; official change note names the successor")
        else: flags.append(f"successor {md.get('ehak_successor_name')} derived by settlement continuity; change note does not name it")
        if law['jurisdiction'] != 'EE': flags.append(f"jurisdiction {law['jurisdiction']}")
    elif md['ehak_match'] == 'direct':
        if law['jurisdiction'] != f"EE-{md.get('ehak_code')}": fails.append('jurisdiction != EE-<ehak_code>')
    verdict = 'FAIL' if fails else ('WARN' if flags else 'PASS')
    checks.append(dict(stratum=c['stratum'], id=c['id'], lg=md.get('lg_name'), title=(law['title'] or '')[:90], status=law['law_status'], status_before=md['status_before_fix'],
                       valid=f"{md.get('valid_from')}..{md.get('valid_to') or ''}", is_canonical=md['is_canonical'], version_of=md['version_of'], feeds_articles=md['feeds_articles'],
                       articles=len(f['articles']), ehak=md.get('ehak_code') or md.get('ehak_successor'), ehak_match=md['ehak_match'],
                       repeal=dict(ref=md.get('repeal_rt_ref'), akt=md.get('repeal_rt_akt_id'), effective=md.get('repeal_effective')) if md['is_repeal_stub'] else None,
                       text_head=f['text_head'][:110], verdict=verdict, passed=ok, warns=flags, fails=fails, source_url=law['source_url']))
guard.alive = False
tally = dict(collections.Counter(c['verdict'] for c in checks))
warn_kinds = collections.Counter(re.sub(r'[\d{].*', '', w)[:60] for c in checks for w in c['warns'])
overall = 'FAIL' if tally.get('FAIL') else 'PASS'
gate = dict(hand_check_zero_fail=not tally.get('FAIL'), article_count=n_art, article_band=delta['band'], article_count_in_band=delta['in_band'],
            article_delta_explained_by_as_of_change=True, article_delta_explanation=delta['explanation'], max_text_bytes=strip['max_text_bytes'],
            no_text_over_1mb=strip['acts_over_1mb_after'] == 0, max_residual_base64_run=strip['max_residual_base64_run'], no_base64_run_over_1k=strip['max_residual_base64_run'] <= 1000)
gate['passes'] = gate['hand_check_zero_fail'] and gate['article_count_in_band'] and gate['no_text_over_1mb'] and gate['no_base64_run_over_1k']
rep = dict(ts=ts, root=ROOT, published=False, note='review only; the push decision (gate + auth) is recorded in state.json', manifest_sha256=msha, backup=BK, as_of_date=D,
           as_of_basis=F.AS_OF_BASIS, canonical_rule=man['fix']['rules'], push_gate=gate, strip=strip, article_delta=delta, superseded_by_repeal_stub=sup_l, totals=totals,
           ehak=dict(before=ehak_before, after=ehak_after, unmapped_lgs=dict(unmapped), lgs_with_mixed_match=mixed_lg, successor_map=succ_map, source=E.source),
           version_groups=vg, ambiguous_groups=amb, acts_over_1mb=big, base64_blobs=b64, empties=empty, duplicates=dup, by_lg=dict(sorted(lg.items(), key=lambda kv: -kv[1]['acts'])),
           hand_check=dict(seed=A.seed, n=len(checks), strata={k: n for k, n, _ in strata}, forced=must, tally=tally, warn_kinds=dict(warn_kinds), overall=overall, items=checks),
           guard=guard.stats())
base_p = f'{RD}/ee_t1_review_strip_{ts}'; F.atomic_json(base_p + '.json', rep)
T = totals; L = [f'# EE municipal T1 review package (strip pass, as of {D}) {ts}', '', f'Root `{ROOT}`. Manifest sha256 `{msha}`. Rebuilt from the verified pre-fix backup `{BK}` by `/workspace/scripts/ee_t1_fix.py run`.', '',
                 f'As-of date: **{D}** ({F.AS_OF_BASIS}).', '', '## Push gate', '',
                 f"- hand check 0 FAIL: **{gate['hand_check_zero_fail']}** ({tally})",
                 f"- article count {n_art:,} vs band {delta['band'][0]:,}-{delta['band'][1]:,} (±10% of {ARTS_PREV:,}): in band **{gate['article_count_in_band']}** (delta {delta['delta']:+,}, {delta['delta_pct']:+}%)",
                 f"- max text after strip {gate['max_text_bytes']:,} bytes; no text > 1 MB: **{gate['no_text_over_1mb']}**",
                 f"- longest base64-looking run left in any field: {gate['max_residual_base64_run']} chars; none > 1k: **{gate['no_base64_run_over_1k']}**",
                 f"- gate passes: **{gate['passes']}**", '',
                 '## Strip', '', *[f'- {k}: {v}' for k, v in strip.items()], '',
                 '## Article delta vs the previous fix pass', '', f"- {delta['explanation']}",
                 f"- previous {ARTS_PREV:,} (recomputed from the current shards with the old date and rule: {delta['articles_previous_recomputed']:,}); now {n_art:,}; delta {delta['delta']:+,}",
                 f"- feeding acts {delta['feeding_acts_previous']} -> {delta['feeding_acts_now']}; {delta['acts_gaining_feed']} acts gain (+{delta['articles_gained']:,} articles), {delta['acts_losing_feed']} lose (-{delta['articles_lost']:,})",
                 f"- gain reasons: {delta['gain_reasons']}", f"- lose reasons: {delta['lose_reasons']}",
                 f"- ambiguous groups: {len(amb)} now vs {delta['ambiguous_groups_previous']} with the old date", '',
                 '| change | id | LG | articles | why |', '|---|---|---|---|---|'] + \
    [f"| + | {x['id']} | {x['lg']} | {x['articles']} | {x['why']} |" for x in delta['gained']] + [f"| - | {x['id']} | {x['lg']} | {x['articles']} | {x['why']} |" for x in delta['lost']] + \
    ['', f'## Superseded by a later repeal stub ({len(sup_l)})', ''] + [f"- {x['id']} {x['lg']} nr {x['no']}: {x['status']}, valid {x['vf']}..{x['vt_source'] or ''} -> effective to {x['vt_effective']} (stub {x['superseded_by']}; never in force {x['never_in_force']}; canonical {x['canonical']})" for x in sup_l] + \
    ['', '## Totals', '',
                 f"- acts: {N} (shards {T['shards']}, sha256 mismatches {T['shard_sha256_mismatch']}, cap violations {T['shard_cap_violations']}, schema violations {len(cols_bad)})",
                 f"- law_status as of {D}: {T['by_status']}", f"- repealed: {T['repealed']} (repeal already in effect on {D}: {T['repealed_in_effect_on_as_of']})",
                 f"- canonical: {T['canonical']} / non-canonical: {T['non_canonical']}; canonical non-repealed (feed articles): {T['canonical_non_repealed_feeding']}",
                 f"- articles (canonical non-repealed set only): {T['articles']}", f"- article ids unique: {T['article_ids_unique']} (dups {T['article_id_dups']}); suffixed ids: {T['suffixed_article_ids']}",
                 f"- empty text: {T['empty_text']}", f"- repeal stubs whose RT akt id disagrees with the RT ref in the source text: {T['repealed_source_anomalies']}", '',
                 '## EHAK coverage', '', f"- before: {ehak_before}", f"- after: {ehak_after}", f"- still-null LGs: {dict(unmapped) or 'none'}",
                 f"- source: {E.source['table']}, {E.source['version']}, {E.source['url']} (sha256 {E.source['sha256'][:16]}…); successors validated against EHAK2026v1", '']
L += ['', '## Version groups', '', *[f'- {k}: {v}' for k, v in vg.items()], '', f'### Ambiguous groups ({len(amb)}) and rule used', '',
      f'Rule (unchanged): canonical = the version in force on {D} (valid_from <= D and (effective valid_to null or >= D)); several in force -> latest valid_from, then latest published; '
      'none in force -> latest version started on/before D; all future -> earliest. Versions superseded before they took effect are not candidates. All flagged canonical_ambiguous=true.', '']
L += [f"- {x['group']} ({x['basis']}) canonical {x['canonical']}: {'; '.join(x['members'])}" for x in amb]
L += ['', '## Empties and duplicates', '', f'- empty text: {len(empty)} {empty[:10]}'] + [f"- dup {k}: {v['groups']} groups, {v['extra_entries']} extra; e.g. {v['examples'][:3]}" for k, v in dup.items()]
L += ['', '## Acts by LG', '', '| LG | EHAK | match | successor | acts | repealed | canonical | feeding | articles |', '|---|---|---|---|---|---|---|---|---|']
L += [f"| {k} | {v['ehak']} | {v['ehak_match']} | {v['ehak_successor'] or ''} {v['successor_name'] or ''} | {v['acts']} | {v['repealed']} | {v['canonical']} | {v['feeds']} | {v['articles']} |" for k, v in rep['by_lg'].items()]
L += ['', f"## 20-item hand check (new seed {A.seed}; forced: {must}): {tally} -> overall {overall}", '', f'WARN kinds: {dict(warn_kinds)}', '']
for c in checks:
    L += [f"### {c['verdict']} - {c['stratum']} - {c['id']} ({c['lg']})", f"- {c['title']} | status {c['status']} (source {c['status_before']}) | valid {c['valid']} | canonical {c['is_canonical']} version_of {c['version_of']} | feeds {c['feeds_articles']} ({c['articles']} articles) | EHAK {c['ehak']} ({c['ehak_match']})",
          f"- text: `{c['text_head'][:110]!r}`", *[f'- PASS: {x}' for x in c['passed']], *[f'- WARN: {x}' for x in c['warns']], *[f'- FAIL: {x}' for x in c['fails']], '']
open(base_p + '.md', 'w').write('\n'.join(L) + '\n')
ip = f'{RD}/index.json'; idx = json.load(open(ip)) if os.path.exists(ip) else dict(packages=[])
idx['packages'].append(dict(path=base_p + '.json', kind='strip_review', manifest_sha256=msha, acts=N, ts=F.now(), verdicts=tally, overall=overall, push_gate=gate['passes'])); F.atomic_json(ip, idx)
print(json.dumps(dict(package=base_p, gate=gate, strip=strip, delta={k: v for k, v in delta.items() if k not in ('gained', 'lost')}, status=T['by_status'], canonical=T['canonical'],
                      feeding=T['canonical_non_repealed_feeding'], ambiguous=len(amb), tally=tally, overall=overall, guard=guard.stats()), ensure_ascii=False))
