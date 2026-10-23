#!/usr/bin/env python3
"""EE municipal T1 OFFLINE fix pass (CoS fix orders 2026-10-06). Works only from existing shards; never downloads RT data, never touches xml.2025/xml.2026,
never pushes/publishes anything. Rerunnable: the source is always the verified pre-fix backup (index/laws_shards_pre_fix_<ts>/), output replaces
index/laws_shards/ee_t1_kov_NNNN.jsonl.gz + manifest.json in place.

Usage (run under nice -n 19):
  ee_t1_fix.py backup                    copy index/laws_shards -> index/laws_shards_pre_fix_<ts>/ and verify sha256 vs manifest (refuses if a fix already ran)
  ee_t1_fix.py run [--src DIR]           pass 1 (metadata) + decisions + pass 2 (rewrite into index/laws_shards_fix_tmp_<ts>/) + verify + in-place swap + re-verify
  ee_t1_fix.py dryrun [--src DIR]        same as run but writes to build/fix_dry_<ts>/ only (no swap, no state change)
  ee_t1_fix.py verify                    re-read index/laws_shards and check the fixed invariants

Fixes
 1 Repeal stubs (text starts with 'Kehtetu'): law_status='repealed' (old status kept in metadata status_before_fix); repeal RT ref parsed from both the
   newline and the run-together format into repeal_rt_part / repeal_published / repeal_rt_article / repeal_rt_akt_id / repeal_rt_ref / repeal_rt_url /
   repeal_effective (+ repeal_note, repeal_format, repeal_checks). Kept as metadata records; never feed articles.
 2 Versions: base key LG + doc type + act number (as ordered), refined by issuer + adoption date (the base key merges distinct acts that share a number,
   e.g. a council and a government regulation nr 7, or nr 14 of 2018 and nr 14 of 2022). Canonical = version in force on AS_OF (valid_from <= D and
   (valid_to null or >= D)); ties -> latest valid_from, then latest published, version_date, meta_version_date, id. No version in force -> latest version
   started on/before D, else earliest future version (flagged canonical_ambiguous). Non-canonical: version_of=<canonical id>, articles=[]; text kept.
   feeds_articles = is_canonical and not repealed.
 3 EHAK: LGs without an EHAK2026v1 code are mapped to their successor with the official Statistics Estonia floating classifier EHAK2017ap (v45) only:
   settlements (4-digit unique codes) of the abolished municipality at its end date -> municipality that holds them in the currently valid rows. Former
   cities that were themselves the municipality (no child settlements) -> the same-name settlement row that starts the day after the city ended (same
   classifier). Unique successor -> mapped; several -> mapped only if the majority holder is also named in the official change note; else null.
   Successor codes validated against EHAK2026v1. Fields: lg_name_original, ehak_match, ehak_successor (+_name, _county, _method), ehak_abolished_code,
   ehak_change_note, ehak_source.
 4 Article ids made unique per act with a deterministic suffix _2, _3 ... in document order (original id kept in article metadata id_original).
   Text size measured (text_bytes, text_over_1mb, text_base64_run_chars = line-wrapped base64 attachment blobs, articles_base64_chars); nothing dropped.
Strip pass (CoS strip orders 2026-10-06; same script, same verified backup as source, rerunnable)
 5 Attachments: every base64 PDF/image blob (line-wrapped data the original parser rendered into law text / article text) is replaced by
   '[attachment: <name>, <mime>, <bytes>, <sha256>]' (bytes + sha256 of the decoded file). The blob itself is not kept anywhere. Name from the XML
   attachment attribute list (metadata attachments) where it can be matched (single file, or same 'Lisa N' number as the text label after the blob, or last
   remaining), else the text label; mime from the decoded magic bytes (checked against the file extension). PDFs are cut at their %%EOF. Per-blob
   metadata list: metadata_json.attachments_stripped (articles: their own list in article metadata_json).
 6 Titles: the RT note appended to <aktinimi> ('<title> YYYY-MM-DD HH:MM[:SS] <note>') moved to metadata title_note (+ title_note_ts); clean title kept.
 7 As-of date AS_OF (2024-11-01) replaces the dump date for statuses + canonical versions (same canonical rule); stored as as_of_date on every record
   and in the manifest. law_status of non-stubs: current = in force on AS_OF, future_version = starts after AS_OF, historical_version = ended before
   AS_OF; stubs stay 'repealed' (repeal_in_effect_as_of says whether the repeal had taken effect on AS_OF).
 8 A version followed by a later-published repeal stub of the same act (stub valid_from >= version valid_from, version valid_to open or >= stub
   valid_from) is superseded: valid_to_effective = stub valid_from - 1 day; if it therefore never entered into force it is historical_version and is
   not a canonical candidate (unless nothing else is). Fields superseded_by_repeal_stub, valid_to_effective, never_in_force.
Memory guard: MemAvailable < 3584 MB -> pause until >= 4200 MB held 30 s; < 3000 MB for >= 5 s (1 s watcher) -> clean stop (old shards untouched);
RSS > 300 MB -> clean stop. Records are streamed one at a time."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, re, json, gzip, time, hashlib, csv, collections, threading, shutil, glob, datetime
ROOT = '{_CORPORA}/ee_municipal'
IDX = f'{ROOT}/index'; SH = f'{IDX}/laws_shards'; MAN = f'{SH}/manifest.json'
AS_OF = '2024-11-01'
AS_OF_BASIS = ('CoS strip orders 2026-10-06: snapshot as of 2024-11-01 = latest publication date (published) in RT avaandmed xml.2024; '
               'statuses and canonical versions are evaluated on this date (the zip itself was generated 2026-10-04)')
DUMP_DATE = AS_OF   # compatibility alias: all date logic now uses the as-of date
SOURCE_GENERATED = '2026-10-04'
SOURCE_GENERATED_BASIS = ('state.json source.last_modified "Sun, 04 Oct 2026 08:12:25 GMT" (= 2026-10-04 01:12:25 PDT / 11:12:25 EEST) of xml.2024.zip, identical to '
                   'ee_municipal_t1.py DUMP_AS_OF="2026-10-04" (LOEMIND: "Riigi Teataja avaandmed on genereeritud 2026-10-04 seisuga") used for status_ref_date')
EHAK_AP = f'{ROOT}/ref/ehak/EHAK2017ap_v45_stat_ee.csv'
EHAK_AP_URL = 'https://klassifikaatorid.stat.ee/item/stat.ee/f356a016-84dd-4290-950f-b7bf667d70f1/45/_classification-csv'
EHAK_26 = f'{ROOT}/ref/ehak_2026v1_stat_ee.csv'
EHAK_26_URL = 'https://klassifikaatorid.stat.ee/item/stat.ee/079ed389-81f0-4171-8442-d8cf7412cdb7/2/_classification-csv'
SHARD_N = 1000; SHARD_MAX = 64 * 1000 * 1000; MB1 = 1000 * 1000
STATUS = 'T1_STRIP_DONE_AWAIT_REVIEW'
STATE_KEY = 't1_strip'
def now(): return time.strftime('%Y-%m-%dT%H:%M:%S%z')
LOGF = None
def log(*a):
    s = time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + ' '.join(str(x) for x in a)
    print(s, flush=True)
    if LOGF:
        with open(LOGF, 'a') as f: f.write(s + '\n')
def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def atomic_json(p, o):
    t = p + '.tmp'
    with open(t, 'w') as f: json.dump(o, f, indent=1, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(t, p)
# ---------------- memory guard ----------------
class Stop(Exception): pass
def memavail():
    with open('/proc/meminfo') as f:
        for l in f:
            if l.startswith('MemAvailable:'): return int(l.split()[1]) // 1024
    return 0
def rss_mb(key='VmRSS'):
    with open('/proc/self/status') as f:
        for l in f:
            if l.startswith(key + ':'): return int(l.split()[1]) // 1024
    return 0
class Guard:
    def __init__(s, pause=3584, resume=4200, hold=30, hard=3000, hard_s=5, rss_limit=300, max_pause=900):
        s.pause, s.resume, s.hold, s.hard, s.hard_s, s.rss_limit, s.max_pause = pause, resume, hold, hard, hard_s, rss_limit, max_pause
        s.min_mem = memavail(); s.peak_rss = rss_mb(); s.stop = None; s.low_t0 = None; s.n_pause = 0; s.pause_s = 0.0; s.alive = True
        threading.Thread(target=s._watch, daemon=True).start()
    def _watch(s):
        while s.alive:
            try:
                m = memavail(); t = time.time(); s.min_mem = min(s.min_mem, m); r = rss_mb(); s.peak_rss = max(s.peak_rss, rss_mb('VmHWM'), r)
                if m < s.hard:
                    s.low_t0 = s.low_t0 or t
                    if t - s.low_t0 >= s.hard_s and not s.stop: s.stop = f'MemAvailable {m} MB < {s.hard} for {t - s.low_t0:.0f}s'; log('GUARD STOP', s.stop)
                else: s.low_t0 = None
                if r > s.rss_limit and not s.stop: s.stop = f'RSS {r} MB > {s.rss_limit}'; log('GUARD STOP', s.stop)
            except Exception as e: log('guard watcher error', repr(e))
            time.sleep(1)
    def gate(s):
        if s.stop: raise Stop(s.stop)
        m = memavail()
        if m >= s.pause: return
        s.n_pause += 1; t0 = time.time(); ok = None; log(f'MEMPAUSE MemAvailable {m} MB < {s.pause}; waiting for >= {s.resume} held {s.hold}s')
        while True:
            time.sleep(1)
            if s.stop: raise Stop(s.stop)
            m = memavail(); t = time.time()
            if t - t0 > s.max_pause: s.stop = f'paused > {s.max_pause}s'; raise Stop(s.stop)
            if m >= s.resume:
                ok = ok or t
                if t - ok >= s.hold: break
            else: ok = None
        s.pause_s += time.time() - t0; log(f'MEMRESUME MemAvailable {m} MB after {time.time() - t0:.0f}s')
    def stats(s): return dict(min_memavail_mb=s.min_mem, peak_rss_mb=max(s.peak_rss, rss_mb('VmHWM')), n_pause=s.n_pause, pause_s=round(s.pause_s, 1), stop=s.stop)
def stream(d, guard):
    """yield (shard_name, record dict) one line at a time from a shard dir (sorted shard names)"""
    for p in sorted(glob.glob(f'{d}/ee_t1_kov_*.jsonl.gz')):
        with gzip.open(p, 'rt', encoding='utf-8') as g:
            for l in g:
                guard.gate(); r = json.loads(l); del l
                yield os.path.basename(p), r
# ---------------- 1. repeal stubs ----------------
RE_NL = re.compile(r'^Kehtetu\n(RT (?:IV|III|II|I))\n(\d{4}-\d{2}-\d{2})(?:[+-]\d{2}:\d{2})?\n(\d+)\n(\d+)\n(\d{4}-\d{2}-\d{2})(.*)$', re.S)
RE_RUN = re.compile(r'^KehtetuRT ?(IV|III|II|I)(\d{4}-\d{2}-\d{2})(?:[+-]\d{2}:\d{2})?(\d+?)(\d{4}-\d{2}-\d{2})(.*)$', re.S)
PART_PREFIX = {'RT I': '1', 'RT II': '2', 'RT III': '3', 'RT IV': '4'}
def is_stub(text): return (text or '').startswith('Kehtetu')
def parse_repeal(text):
    """-> dict of repeal_* fields (repeal_parse_ok False if neither format matches)"""
    m = RE_NL.match(text); fmt = 'newline'
    if m: part, pub, art, akt, eff, rest = m.groups()
    else:
        m = RE_RUN.match(text); fmt = 'run_together'
        if not m: return dict(repeal_parse_ok=False, repeal_format=None)
        roman, pub, digits, eff, rest = m.groups(); part = f'RT {roman}'
        pre = PART_PREFIX[part] + pub[8:10] + pub[5:7] + pub[:4]     # RT akt id = part digit + ddmmyyyy (publication) + nnn (article)
        i = digits.find(pre, 1)
        if i > 0: art, akt = digits[:i], digits[i:]
        else:                                                         # fallback: last 12 digits are the akt id
            art, akt = digits[:-12], digits[-12:]
    exp = PART_PREFIX.get(part, '?') + pub[8:10] + pub[5:7] + pub[:4] + f'{int(art):03d}' if art.isdigit() else None
    checks = dict(akt_id_12_digits=len(akt) == 12, akt_id_encodes_publication=akt[1:9] == pub[8:10] + pub[5:7] + pub[:4],
                  akt_id_encodes_article=akt.isdigit() and len(akt) == 12 and int(akt[9:]) == int(art), akt_id_part_digit=akt[:1] == PART_PREFIX.get(part))
    rest = rest or ''; note = None; trailing = None
    mm = re.match(r'^\s*,\s*(rakend[^\n]*)', rest)
    if mm: note = mm.group(1).strip(); rest = rest[mm.end():]
    if rest.strip(): trailing = dict(chars=len(rest.strip()), attachment_placeholder=rest.strip().startswith('[attachment:'), head=rest.strip()[:160])
    d = dict(repeal_parse_ok=True, repeal_format=fmt, repeal_rt_part=part, repeal_published=pub, repeal_rt_article=str(int(art)), repeal_rt_akt_id=akt,
             repeal_rt_ref=f'{part}, {pub[8:10]}.{pub[5:7]}.{pub[:4]}, {int(art)}', repeal_rt_url=f'https://www.riigiteataja.ee/akt/{akt}', repeal_effective=eff,
             repeal_note=note, repeal_checks=checks, repeal_checks_ok=all(checks.values()))
    if not checks['akt_id_12_digits'] or not checks['akt_id_encodes_article']: d['repeal_rt_akt_id_expected'] = exp
    if trailing: d['repeal_trailing_text'] = trailing
    return d
# ---------------- 2. versions ----------------
def in_force(r, d=AS_OF): return bool(r['vf']) and r['vf'] <= d and (not r['vt'] or r['vt'] >= d)
def ver_key(r): return (r['vf'] or '', r['pub'] or '', (r['vd'] or '')[:10], (r['mvd'] or '')[:10], r['id'])
def base_key(r): return f"{r['lg']}|{r['dt']}|{r['no']}"
def group_key(r): return f"{r['lg']}|{r['dt']}|{r['no']}|{re.sub(r'\\s+', ' ', (r['issuer'] or '').strip().lower())}|{r['adopted']}"
def decide_versions(rows, d=AS_OF):
    """rows: vt = effective valid_to (after repeal-stub supersession), never = superseded before it entered into force (not a canonical candidate)"""
    groups = collections.defaultdict(list)
    for r in rows: groups[group_key(r)].append(r)
    dec = {}; amb = []
    for k, v in groups.items():
        cand = [r for r in v if not r.get('never')] or v
        inf = [r for r in cand if in_force(r, d)]
        if len(inf) == 1: c = inf[0]; basis = 'in_force_on_as_of_date'
        elif inf: c = max(inf, key=ver_key); basis = 'in_force_on_as_of_date:tie->latest_valid_from_then_latest_published'
        else:
            st = [r for r in cand if r['vf'] and r['vf'] <= d]
            if st: c = max(st, key=ver_key); basis = 'fallback_none_in_force:latest_started_before_as_of'
            else: c = min(cand, key=ver_key); basis = 'fallback_none_in_force:all_future->earliest'
        order = sorted(v, key=ver_key)
        for i, r in enumerate(order):
            dec[r['id']] = dict(version_group_key=k, version_group_base_key=base_key(r), version_group_size=len(v), version_rank=i + 1, is_canonical=r['id'] == c['id'],
                                version_of=None if r['id'] == c['id'] else c['id'], canonical_id=c['id'], canonical_basis=basis, canonical_ambiguous=not basis.startswith('in_force_on_as_of_date') or len(inf) > 1,
                                in_force_as_of=in_force(r, d), as_of_date=d, n_in_force_in_group=len(inf))
        if len(inf) != 1: amb.append(dict(key=k, size=len(v), n_in_force=len(inf), basis=basis, canonical=c['id'],
                                          members=[dict(id=r['id'], vf=r['vf'], vt=r['vt'], vt_source=r.get('vt_src', r['vt']), never_in_force=bool(r.get('never')), stub=r['stub'], published=r['pub'],
                                                       status=r.get('st_new', r['st'])) for r in order]))
    return dec, groups, amb
def dshift(x, n): return (datetime.date.fromisoformat(x) + datetime.timedelta(days=n)).isoformat()
def supersede(rows):
    """order 8: version followed by a later-published repeal stub of the same act -> {id: supersession fields}"""
    g = collections.defaultdict(list)
    for r in rows: g[group_key(r)].append(r)
    out = {}
    for v in g.values():
        stubs = [x for x in v if x['stub'] and x['vf']]
        for r in v:
            if r['stub'] or not r['vf']: continue
            c = [x for x in stubs if (x['pub'] or '') > (r['pub'] or '') and x['vf'] >= r['vf'] and (not r['vt'] or r['vt'] >= x['vf'])]
            if c:
                x = min(c, key=lambda x: (x['vf'], x['pub'] or '', x['id'])); vte = dshift(x['vf'], -1)
                out[r['id']] = dict(superseded_by_repeal_stub=x['id'], superseded_repeal_published=x['pub'], superseded_repeal_effective=x['vf'],
                                    valid_to_source=r['vt'], valid_to_effective=vte, never_in_force=vte < r['vf'])
    return out
def status_as_of(x, d=AS_OF):
    if x['stub']: return 'repealed'
    if not x['vf']: return 'unknown'
    if x.get('never'): return 'historical_version'
    if x['vf'] > d: return 'future_version'
    if x['vt'] and x['vt'] < d: return 'historical_version'
    return 'current'
# ---------------- 3. EHAK ----------------
def load_ehak26():
    m = {}
    for x in csv.DictReader(open(EHAK_26, encoding='utf-8-sig')):
        if x['Level'] == '2' and not x['Label-et-EE'].endswith('linnaosa'): m[x['Value']] = dict(name=x['Label-et-EE'], county=x['Parent'])
    return m
class EhakAP:
    MUN = ('01', '04')
    def __init__(s):
        s.rows = list(csv.DictReader(open(EHAK_AP, encoding='utf-8-sig'))); s.sha = sha_file(EHAK_AP); s.e26 = load_ehak26()
        s.by_label = collections.defaultdict(list); s.by_m4 = collections.defaultdict(list); s.by_settl = collections.defaultdict(list); s.mun_cur = {}
        for r in s.rows:
            v = r['Value']; s.by_label[r['Label-et-EE']].append(r); s.by_m4[v[4:8]].append(r)
            if v[-2:] not in s.MUN + ('00',): s.by_settl[v[8:12]].append(r)
            if not r['ValidTo'] and v[-2:] in s.MUN: s.mun_cur[v[4:8]] = r
        s.source = dict(table='Statistikaamet EHAK2017ap - Eesti haldus- ja asustusjaotuse klassifikaator aegpidev 2017 (floating classifier with change notes)',
                        version='klassifikaatorid.stat.ee version 45 (updated 2026-08-27T10:54:59Z)', url=EHAK_AP_URL, local_file=EHAK_AP.replace(ROOT + '/', ''),
                        sha256=s.sha, successor_validated_against=f'EHAK2026v1 {EHAK_26_URL}')
    def mun_row(s, name, adopted):
        c = [r for r in s.by_label.get(name, []) if r['Value'][-2:] in s.MUN]
        if not c:   # e.g. 'Vandra alev': the label is a settlement row whose municipality code has its own municipality row 'Vandra vald (alev)'
            for r in s.by_label.get(name, []):
                c += [x for x in s.by_m4[r['Value'][4:8]] if x['Value'][-2:] in s.MUN]
            c = list({x['Value']: x for x in c}.values())
        if not c: return None
        ab = [r for r in c if r['ValidTo']]
        if not ab: return None
        cont = [r for r in ab if adopted and r['ValidFrom'] <= adopted <= r['ValidTo']]
        return (cont or sorted(ab, key=lambda r: r['ValidTo']))[-1]
    @staticmethod
    def _d(x, n): return (datetime.date.fromisoformat(x) + datetime.timedelta(days=n)).isoformat()
    def step(s, M):
        """municipality row M (abolished) -> (Counter of next municipality codes, method, n settlements). Uses only EHAK2017ap rows: each settlement
        (4-digit unique code) of M that ended within 7 days before M's end -> the row of the same settlement starting the next day -> its municipality."""
        m4, T = M['Value'][4:8], M['ValidTo']; lo = s._d(T, -7)
        kids = [r for r in s.by_m4[m4] if r['Value'][-2:] not in s.MUN + ('00',) and r['ValidTo'] and r['ValidFrom'] <= T and lo <= r['ValidTo'] <= T]
        method = 'settlement_continuity'
        if not kids:   # a former city that was itself the municipality (no child settlements): same-label settlement row starting the next day
            kids = [dict(M, _code=None)]; method = 'city_became_settlement_continuity'
        cand = collections.Counter(); n = 0
        for k in kids:
            nxt = s._d(k['ValidTo'], 1)
            if k.get('_code', 1) is None: hits = [r for r in s.by_label.get(M['Label-et-EE'].split(' (')[0], []) if r['Value'][-2:] not in s.MUN + ('00',) and r['ValidFrom'] == nxt]
            else: hits = [r for r in s.by_settl[k['Value'][8:12]] if r['ValidFrom'] == nxt and r['Value'][-2:] not in s.MUN + ('00',)]
            if hits: n += 1
            for r in hits[:1]: cand[r['Value'][4:8]] += 1
        return cand, method, n, nxt if kids else None
    def mun_by_code_at(s, code, d):
        c = [r for r in s.by_m4[code] if r['Value'][-2:] in s.MUN]
        c2 = [r for r in c if r['ValidFrom'] <= d and (not r['ValidTo'] or r['ValidTo'] >= d)]
        return (c2 or c or [None])[-1]
    def successor(s, name, adopted):
        M = s.mun_row(name, adopted)
        if M is None: return dict(ehak_match='unmapped', ehak_unmapped_reason='no abolished municipality row with this name in EHAK2017ap')
        base = dict(ehak_abolished_code=M['Value'][4:8], ehak_abolished_name=M['Label-et-EE'], ehak_abolished_valid=f"{M['ValidFrom']}..{M['ValidTo']}",
                    ehak_change_note=M['Description-et-EE'][:400])
        chain = []; methods = []; cur = M
        for _ in range(6):
            cand, method, n, nxt = s.step(cur)
            link = dict(from_code=cur['Value'][4:8], from_name=cur['Label-et-EE'], ended=cur['ValidTo'], settlements_traced=n,
                        candidates={k: v for k, v in cand.items()}, note=cur['Description-et-EE'][:300])
            chain.append(link)
            if not cand: return dict(base, ehak_match='unmapped', ehak_unmapped_reason='no settlement continuity in EHAK2017ap', ehak_chain=chain)
            code, top = cand.most_common(1)[0]
            if len(cand) > 1:
                nm = s.mun_by_code_at(code, nxt)
                stem = (nm['Label-et-EE'] if nm else '').rsplit(' ', 1)[0]
                if cand.most_common(2)[1][1] == top or not stem or stem not in cur['Description-et-EE']:
                    return dict(base, ehak_match='unmapped', ehak_chain=chain,
                                ehak_unmapped_reason='split between several successors and the change note does not confirm the majority holder')
                method += '_majority_confirmed_by_change_note'
            link['to_code'] = code; methods.append(method)
            if code in s.mun_cur: break
            cur = s.mun_by_code_at(code, nxt)
            if cur is None or not cur['ValidTo']: return dict(base, ehak_match='unmapped', ehak_unmapped_reason=f'chain broken at {code}', ehak_chain=chain)
        else: return dict(base, ehak_match='unmapped', ehak_unmapped_reason='chain too long', ehak_chain=chain)
        e = s.e26.get(code); cur_name = s.mun_cur[code]['Label-et-EE']
        if not e: return dict(base, ehak_match='unmapped', ehak_unmapped_reason=f'successor {code} not in EHAK2026v1', ehak_chain=chain)
        if cur_name != e['name']: return dict(base, ehak_match='unmapped', ehak_unmapped_reason=f'name mismatch 2017ap {cur_name} vs 2026v1 {e["name"]}', ehak_chain=chain)
        return dict(base, ehak_match='successor', ehak_successor=code, ehak_successor_name=e['name'], ehak_successor_county=e['county'],
                    ehak_successor_method=' -> '.join(methods), ehak_chain=chain, ehak_chain_len=len(chain))
# ---------------- 4. articles ----------------
def dedup_articles(arts):
    seen = collections.Counter(); n_changed = 0; out = []
    for a in arts:
        i = a['id']; seen[i] += 1
        if seen[i] > 1:
            a = dict(a); md = json.loads(a['metadata_json']); md['id_original'] = i; md['id_dedup_suffix'] = f'_{seen[i]}'
            a['id'] = f'{i}_{seen[i]}'; a['metadata_json'] = json.dumps(md, ensure_ascii=False); n_changed += 1
        out.append(a)
    assert len({a['id'] for a in out}) == len(out), 'suffix collision'
    return out, n_changed
B64LINE = re.compile(r'^[A-Za-z0-9+/]{60,}={0,2}$', re.M)   # line-wrapped base64 (embedded PDF/image attachments rendered into the text)
def b64_chars(t): return sum(len(z) for z in B64LINE.findall(t or ''))
# ---------------- 5. attachment blob strip ----------------
import base64, binascii, bisect
B64SPAN = re.compile(r'[A-Za-z0-9+/=\r\n]{200,}')
B64ANY = re.compile(r'[A-Za-z0-9+/=\r\n]{1000,}')
MAGIC_B64 = ['JVBERi0', 'iVBORw0KGgo', '/9j/', 'UEsDB', '0M8R4KGxGuE', 'R0lGOD', 'SUkqA', 'TU0AK', 'e1xydGY']
MAGIC = [(b'%PDF', 'application/pdf'), (b'\x89PNG', 'image/png'), (b'\xff\xd8\xff', 'image/jpeg'), (b'GIF8', 'image/gif'), (b'PK\x03\x04', 'application/zip'),
         (b'\xd0\xcf\x11\xe0', 'application/x-ole-storage'), (b'II*\x00', 'image/tiff'), (b'MM\x00*', 'image/tiff'), (b'{\\rtf', 'application/rtf')]
EXT_MIME = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'tif': 'image/tiff', 'tiff': 'image/tiff',
            'zip': 'application/zip', 'asice': 'application/vnd.etsi.asic-e+zip', 'bdoc': 'application/vnd.etsi.asic-e+zip', 'ddoc': 'application/x-ddoc', 'rtf': 'application/rtf'}
LABELW = re.compile(r'(Lisa|LISA|lisa|Lisad|LISAD)')
EOFRE = re.compile(rb'%%EOF[\r\n\x00 \t]*$')
LISA_N_TEXT = re.compile(r'^\s*(?:Lisa|LISA|lisa)\s*(?:nr\.?\s*)?(\d+)\b')
STOPW = ['vald', 'valla', 'linn', 'linna', 'vallavalitsus', 'vallavolikogu', 'linnavolikogu', 'aastateks', 'uus', 'kohta']
LISA_N_FILE = re.compile(r'(?i)(?:lisa[\s_.-]*(?:nr\.?\s*)?|^L)(\d+)')
def sniff(b):
    for m, mime in MAGIC:
        if b.startswith(m): return mime
    return 'application/octet-stream'
def b64dec(x):
    try: return base64.b64decode(x, validate=True)
    except (binascii.Error, ValueError): return None
def long_lines(span, n=60): return sum(1 for z in span.split('\n') if len(z.strip()) >= n)
def residual_b64(t):
    """longest base64-looking run in t (line breaks allowed, not counted)"""
    best = 0
    for mo in B64ANY.finditer(t or ''):
        best = max(best, len(mo.group(0)) - mo.group(0).count('\n') - mo.group(0).count('\r'))
    return best
def _cut(s, n):
    """best end (multiple of 4) of the base64 file in s[:n] -> (k, data, mime, eof_ok) or None"""
    eq = s.find('=', 0, n)
    if eq >= 0:
        e = eq
        while e < n and s[e] == '=' and e - eq < 2: e += 1
        n = e
    zone = max(0, n - 120); cands = [n] if eq >= 0 else []
    cands += [mo.start() for mo in LABELW.finditer(s, zone, n)]
    cands += [k for k in range(n, zone, -1) if k % 4 == 0]
    m0 = max(0, zone - 400); m0 -= m0 % 4
    head = b64dec(s[:m0]) if m0 else b''
    if head is None: return None
    best = None; seen = set()
    for k in cands:
        if k in seen or k <= m0 or k % 4: continue
        seen.add(k); t = b64dec(s[m0:k])
        if t is None: continue
        d = head + t; mime = sniff(d); ok = mime != 'application/pdf' or bool(EOFRE.search(d[-64:]))
        if ok: return (k, d, mime, True)
        if best is None: best = (k, d, mime, False)
    return best
def blob_bounds(span):
    """first base64 file in a span of base64-ish chars -> (start, end, data, info) in span offsets, or None"""
    st = None
    for m in MAGIC_B64:
        i = span.find(m, 0, 400)
        if i >= 0 and (st is None or i < st): st = i
    if st is None: st = 0
    sub = span[st:] if st else span
    F = []; i = 0                                   # flat index of each removed line break (memory-light position map)
    for mo in re.finditer(r'[\r\n]', sub): F.append(mo.start() - i); i += 1
    s = sub.replace('\r', '').replace('\n', '') if F else sub; n = len(s); del sub
    if n < 160: return None
    lims = []; j = s.find('JVBERi0', 8)
    if j > 0: lims.append(j)
    lims.append(n); res = None
    for lim in lims:
        r = _cut(s, lim)
        if r and (r[3] or lim == n): res = r; break
    if res is None: return None
    k, d, mime, ok = res
    if mime == 'application/octet-stream' and long_lines(span) < 3: return None
    return st, st + (k - 1) + bisect.bisect_right(F, k - 1) + 1, d, dict(mime=mime, pdf_eof_ok=ok, base64_chars=k)
def _label_after(text, b):
    seg = text[b:b + 400].split('\n'); out = []
    for z in seg:
        z = z.strip()
        if z: out.append(z)
        if len(out) == 2: break
    lab = ' '.join(out)
    return lab[:160] if LABELW.match(lab) else (out[0][:160] if out and LABELW.match(out[0]) else None)
def strip_attachments(text, files, location):
    """-> (text with placeholders, [attachment entries]); blobs are dropped"""
    if not text or len(text) < 200: return text, []
    found = []
    for mo in B64SPAN.finditer(text):
        span = mo.group(0); base = mo.start(); off = 0
        while len(span) - off >= 200:
            r = blob_bounds(span[off:])
            if r is None:
                rest = span[off:]
                if long_lines(rest) >= 3:   # base64-looking but undecodable: still removed, recorded as decode_ok=False
                    ls = [i for i, z in enumerate(rest.split('\n')) if len(z.strip()) >= 60]; lines = rest.split('\n')
                    a = sum(len(z) + 1 for z in lines[:ls[0]]); e = sum(len(z) + 1 for z in lines[:ls[-1] + 1]) - 1
                    raw = re.sub(r'\s', '', rest[a:e]); found.append((base + off + a, base + off + e, None, dict(mime=None, pdf_eof_ok=False, base64_chars=len(raw),
                                                                                                              b64_sha256=hashlib.sha256(raw.encode()).hexdigest())))
                break
            st, en, d, info = r
            found.append((base + off + st, base + off + en, d, info)); off += en
    if not found: return text, []
    files = [f for f in (files or []) if re.search(r'\.(pdf|png|jpe?g|gif|tiff?|zip|asice|bdoc|ddoc|rtf)$', f, re.I)]
    ents = []
    for i, (a, b, d, info) in enumerate(found):
        e = dict(index=i + 1, location=location, label=_label_after(text, b), mime=info['mime'], bytes=len(d) if d is not None else None,
                 sha256=hashlib.sha256(d).hexdigest() if d is not None else None, base64_chars=info['base64_chars'], decode_ok=d is not None,
                 pdf_eof_ok=info['pdf_eof_ok'] if info['mime'] == 'application/pdf' else None, name=None, name_source=None)
        if d is None: e['base64_text_sha256'] = info['b64_sha256']
        ents.append(e)
    # naming works on distinct decoded files (the same attachment can be rendered twice, e.g. in an article and at the end of the text)
    units = collections.OrderedDict()
    for e in ents: units.setdefault(e['sha256'] or f"undecoded{e['index']}", []).append(e)
    units = list(units.values())
    def ulabel(u):   # None if the same file is followed by different labels (e.g. rendered twice, once before 'Lisa 1' and once before 'Lisa 2')
        ls = list(dict.fromkeys(e['label'] for e in u if e['label']))
        if len(ls) > 1: return None
        return ls[0] if ls else None
    def setn(u, name, src):
        for e in u: e.update(name=name, name_source=src)
        used.add(name)
    used = set()
    if len(units) == 1 and len(files) == 1: setn(units[0], files[0], 'xml_attachment:single_file')
    else:
        fnum = collections.defaultdict(list)
        for f in files:
            m = LISA_N_FILE.search(f)
            if m: fnum[int(m.group(1))].append(f)
        for u in units:
            m = LISA_N_TEXT.match(ulabel(u) or '')
            if m:
                c = [f for f in fnum.get(int(m.group(1)), []) if f not in used]
                if len(c) == 1: setn(u, c[0], 'xml_attachment:lisa_number_matches_text_label')
        # word overlap (Jaccard on content words; LG-name words, 'lisa*' and digits ignored), mutual unique best only
        stop = set(STOPW)
        def toks(x): return {w for w in re.findall(r'[^\W\d_]{4,}', (x or '').lower()) if w not in stop and not w.startswith('lisa') and w != 'pdf'} | \
                            {w for w in re.findall(r'[^\W\d_]{4,}', (x or '').lower()) if w.startswith('lisa') and len(w) > 6}
        for _ in range(3):
            un = [u for u in units if not u[0]['name'] and ulabel(u)]; left = [f for f in files if f not in used]
            if not un or not left: break
            sc = {(i, f): (lambda A, B: len(A & B) / len(A | B) if A | B else 0)(toks(ulabel(u)), toks(f.rsplit('.', 1)[0])) for i, u in enumerate(un) for f in left}
            hit = False
            for i, u in enumerate(un):
                row = sorted(((sc[i, f], f) for f in left), reverse=True)
                if not row or row[0][0] == 0 or (len(row) > 1 and row[1][0] == row[0][0]): continue
                f = row[0][1]; col = sorted((sc[j, f] for j in range(len(un))), reverse=True)
                if len(col) > 1 and col[1] == col[0]: continue
                if f not in used: setn(u, f, 'xml_attachment:label_words_match_filename'); hit = True
            if not hit: break
        left = [f for f in files if f not in used]; un = [u for u in units if not u[0]['name']]
        if len(left) == 1 and len(un) == 1: setn(un[0], left[0], 'xml_attachment:last_remaining')
    for e in ents:
        if not e['name']:
            labs = list(dict.fromkeys(z['label'] for z in ents if z['sha256'] == e['sha256'] and z['label'])) if e['sha256'] else ([e['label']] if e['label'] else [])
            if len(labs) > 1: e.update(name=f"attachment_{e['index']}", name_source='none:same_file_followed_by_different_labels', labels_seen=labs)
            elif labs: e.update(name=labs[0][:120], name_source='text_label_after_blob')
            else: e.update(name=f"attachment_{e['index']}", name_source='none')
        ext = e['name'].rsplit('.', 1)[-1].lower() if e['name_source'].startswith('xml') and '.' in e['name'] else None
        e['mime_source'] = 'magic_bytes' + (f'; xml filename extension .{ext} ' + ('agrees' if EXT_MIME.get(ext) == e['mime'] else 'DISAGREES') if ext else '')
        e['placeholder'] = (f"[attachment: {e['name']}, {e['mime']}, {e['bytes']}, {e['sha256']}]" if e['decode_ok'] else
                            f"[attachment: {e['name']}, unknown (undecodable base64), {e['base64_chars']} base64 chars, base64-text sha256 {e['base64_text_sha256']}]")
    out = []; pos = 0
    for (a, b, d, info), e in zip(found, ents):
        pre = text[pos:a]; out.append(pre)
        if pre and not pre.endswith('\n'): out.append('\n')
        out.append(e['placeholder'])
        if b < len(text) and text[b] != '\n': out.append('\n')
        pos = b
    out.append(text[pos:])
    return ''.join(out), ents
# ---------------- 6. title note ----------------
TITLE_NOTE = re.compile(r'^(?P<t>.*?\S)\s+(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?)\s+(?P<note>\S.*)$', re.S)
def split_title(title):
    m = TITLE_NOTE.match(title or '')
    if not m: return title, None
    note = m.group('note').strip()
    kind = 'kehtetu_mark' if 'Kehtetu' in note else 'veaparandus' if 'Veaparandus' in note or 'veaparanduse' in note else 'other'
    return m.group('t').strip(), dict(title_note=note, title_note_ts=m.group('ts'), title_note_kind=kind)
def iter_str(o):
    if isinstance(o, str): yield o
    elif isinstance(o, dict):
        for v in o.values(): yield from iter_str(v)
    elif isinstance(o, list):
        for v in o: yield from iter_str(v)
# ---------------- backup ----------------
def backup():
    st = json.load(open(f'{ROOT}/state.json'))
    if (st.get('t1_fix') or {}).get('done'): sys.exit('REFUSED: fix already applied; a new backup would capture fixed shards. Use the existing backup.')
    man = json.load(open(MAN))
    if man.get('fix'): sys.exit('REFUSED: manifest already carries a fix block')
    ts = time.strftime('%Y%m%dT%H%M%S'); dst = f'{IDX}/laws_shards_pre_fix_{ts}'; os.makedirs(dst)
    for n in sorted(os.listdir(SH)):
        if n.endswith('.jsonl.gz') or n == 'manifest.json': shutil.copy2(f'{SH}/{n}', f'{dst}/{n}')
    bad = []
    for n, s in man['shards'].items():
        h = sha_file(f'{dst}/{n}')
        if h != s['sha256']: bad.append(n)
    msha_src, msha_dst = sha_file(MAN), sha_file(f'{dst}/manifest.json')
    res = dict(created=now(), src=SH, dst=dst, files=sorted(os.listdir(dst)), shard_sha256_ok=not bad, bad=bad, manifest_sha256=msha_dst, manifest_identical=msha_src == msha_dst,
               bytes=sum(os.path.getsize(f'{dst}/{n}') for n in os.listdir(dst)))
    atomic_json(f'{dst}/BACKUP_VERIFY.json', res); print(json.dumps(res, indent=1))
    if bad or msha_src != msha_dst: sys.exit('BACKUP VERIFY FAILED')
    return dst
# ---------------- run ----------------
def latest_backup():
    c = sorted(d for d in glob.glob(f'{IDX}/laws_shards_pre_fix_*') if os.path.isdir(d) and os.path.exists(f'{d}/BACKUP_VERIFY.json'))
    if not c: sys.exit('no verified backup; run `backup` first')
    return c[-1]
def run(src, dry=False):
    global LOGF
    ts = time.strftime('%Y%m%dT%H%M%S'); LOGF = f'/workspace/logs/ee_t1_fix_{ts}{"_dry" if dry else ""}.log'
    bv = json.load(open(f'{src}/BACKUP_VERIFY.json')); assert bv['shard_sha256_ok'] and bv['manifest_identical']
    sman = json.load(open(f'{src}/manifest.json'))
    for n, s in sman['shards'].items():
        if sha_file(f'{src}/{n}') != s['sha256']: sys.exit(f'source shard {n} sha256 mismatch')
    guard = Guard(); log('EE T1 FIX+STRIP START pid', os.getpid(), 'src', src, 'as_of', AS_OF, 'mem', memavail())
    if not dry:
        st = json.load(open(f'{ROOT}/state.json')); st[STATE_KEY] = dict(status='T1_STRIP_RUNNING', started=now(), log=LOGF, src_backup=src, script=os.path.abspath(__file__))
        atomic_json(f'{ROOT}/state.json', st)
    tmp = f'{ROOT}/build/fix_dry_{ts}' if dry else f'{IDX}/laws_shards_fix_tmp_{ts}'
    try:
        # ---- pass 1: compact metadata
        rows = []; old_status = collections.Counter()
        for _, r in stream(src, guard):
            law = r['law']; md = json.loads(law['metadata_json']); t = law['text'] or ''
            x = dict(id=law['id'], lg=md.get('lg_name'), dt=md.get('doc_type'), no=md.get('act_no'), issuer=md.get('issuer'), adopted=md.get('adopted'), vf=md.get('valid_from'),
                     vt=md.get('valid_to'), pub=md.get('published'), vd=md.get('version_date'), mvd=md.get('meta_version_date'), st=law['law_status'], stub=is_stub(t),
                     ehak=md.get('ehak_code'), n_art=len(r['articles']), n_art_ids=len({a['id'] for a in r['articles']}))
            rows.append(x); old_status[law['law_status']] += 1
            del r, law, md, t
        assert len(rows) == sman.get('n_laws', len(rows)) and len({x['id'] for x in rows}) == len(rows)
        sup = supersede(rows)
        for x in rows:
            x['vt_src'] = x['vt']
            if x['id'] in sup: x['vt'] = sup[x['id']]['valid_to_effective']; x['never'] = sup[x['id']]['never_in_force']
            x['st_new'] = status_as_of(x)
        new_status = collections.Counter(x['st_new'] for x in rows)
        log('PASS1 records', len(rows), 'stubs', sum(x['stub'] for x in rows), 'source status', dict(old_status), 'as-of status', dict(new_status),
            'superseded', len(sup), 'never_in_force', sum(v['never_in_force'] for v in sup.values()), 'rss', rss_mb(), 'mem', memavail())
        rowmap = {x['id']: x for x in rows}
        dec, groups, amb = decide_versions(rows)
        ehak = EhakAP(); emap = {}
        for x in rows:
            if not x['ehak']:
                k = (x['lg'], x['adopted'])
                if k not in emap: emap[k] = ehak.successor(x['lg'], x['adopted'])
        log('DECIDE groups', len(groups), 'multi', sum(1 for v in groups.values() if len(v) > 1), 'ambiguous', len(amb), 'ehak keys', len(emap),
            'mapped', sum(1 for v in emap.values() if v['ehak_match'] == 'successor'))
        # ---- pass 2: rewrite
        os.makedirs(tmp); shards = {}; k = 0; cur = None
        def close(cur):
            cur['g'].close(); cur['raw'].flush(); os.fsync(cur['raw'].fileno()); cur['raw'].close()
            p = cur['path']; shards[os.path.basename(p)] = dict(n_laws=cur['n'], n_articles=cur['na'], n_empty_text=cur['ne'], n_repealed=cur['nrep'], n_canonical=cur['ncan'],
                         n_feeds_articles=cur['nfeed'], unpacked_bytes=cur['ub'], bytes=os.path.getsize(p), sha256=sha_file(p), lg_counts=dict(cur['lgs']), ids=cur['ids'], packed_at=now())
            log('SHARD', os.path.basename(p), {kk: vv for kk, vv in shards[os.path.basename(p)].items() if kk not in ('lg_counts', 'ids')}, 'rss', rss_mb(), 'mem', memavail())
        def opn(k):
            p = f'{tmp}/ee_t1_kov_{k:04d}.jsonl.gz'; raw = open(p, 'wb')
            return dict(path=p, raw=raw, g=gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=6, mtime=0), n=0, na=0, ne=0, nrep=0, ncan=0, nfeed=0, ub=0, lgs=collections.Counter(), ids=[])
        agg = collections.Counter(); art_ids_fixed = []; big = []; repeal_bad = []; b64 = []; att_log = []; titles = []; maxt = dict(bytes=0, id=None)
        for _, r in stream(src, guard):
            law = r['law']; md = json.loads(law['metadata_json']); t = law['text'] or ''; arts = r['articles']; lid = law['id']; x = rowmap[lid]
            md['fix'] = dict(script='ee_t1_fix.py', ts=ts, orders='CoS fix orders 2026-10-06 + CoS strip orders 2026-10-06', src_backup=os.path.basename(src))
            # order 6: title note
            ct, tn = split_title(law['title'])
            if tn: md.update(tn); law['title'] = ct; titles.append(dict(id=lid, kind=tn['title_note_kind'])); agg['titles_cleaned'] += 1
            # order 5: attachments in law text
            tb0 = len(t.encode('utf-8')); t, ents = strip_attachments(t, md.get('attachments'), 'text'); law['text'] = t
            stub = is_stub(t); md['status_before_fix'] = law['law_status']
            # order 7/8: as-of status
            law['law_status'] = x['st_new']
            md.update(as_of_date=AS_OF, status_ref_date=AS_OF, status_ref_date_basis=AS_OF_BASIS, source_generated=SOURCE_GENERATED)
            if lid in sup: md.update(sup[lid])
            else: md.update(superseded_by_repeal_stub=None, valid_to_effective=x['vt'], never_in_force=False)
            md['law_status_basis'] = (f'repeal stub (law_status repealed regardless of date)' if stub else
                                      f"as of {AS_OF}: valid_from {x['vf']} / valid_to_effective {x['vt']}" + (' (superseded by repeal stub ' + sup[lid]['superseded_by_repeal_stub'] + ')' if lid in sup else ''))
            if stub:
                p = parse_repeal(t); md.update(p); md['is_repeal_stub'] = True
                md['repeal_in_effect_as_of'] = bool(p.get('repeal_effective')) and p['repeal_effective'] <= AS_OF
                if not p.get('repeal_parse_ok') or not p.get('repeal_checks_ok'): repeal_bad.append(dict(id=lid, text=t[:120], checks=p.get('repeal_checks')))
            else: md['is_repeal_stub'] = False
            md.update(dec[lid])
            feeds = dec[lid]['is_canonical'] and law['law_status'] != 'repealed'
            md['feeds_articles'] = feeds; md['articles_parsed_n'] = len(arts)
            if feeds:
                arts, nchg = dedup_articles(arts)
                if nchg: art_ids_fixed.append(dict(id=lid, lg=md.get('lg_name'), suffixed=nchg))
                out = []
                for a in arts:
                    at, aents = strip_attachments(a['text'] or '', md.get('attachments'), f"article:{a['id']}")
                    if aents:
                        a = dict(a); a['text'] = at; amd = json.loads(a['metadata_json']); amd['attachments_stripped'] = [{kk: vv for kk, vv in e.items() if kk != 'placeholder'} for e in aents]
                        a['metadata_json'] = json.dumps(amd, ensure_ascii=False); ents += aents
                    out.append(a)
                arts = out
            else:
                arts = []
            law['article_count'] = len(arts)
            md['attachments_stripped'] = [{kk: vv for kk, vv in e.items() if kk != 'placeholder'} for e in ents]; md['attachments_stripped_n'] = len(ents)
            for e in ents:
                agg['blobs_removed'] += 1; agg['blob_bytes_decoded'] += e['bytes'] or 0; agg['blob_base64_chars'] += e['base64_chars']; agg[f"blob_mime:{e['mime']}"] += 1
                agg[f"blob_name_source:{e['name_source']}"] += 1; agg['blob_decode_failed'] += not e['decode_ok']; agg['blob_pdf_no_eof'] += e['pdf_eof_ok'] is False
                agg['blobs_in_articles'] += e['location'] != 'text'
                att_log.append(dict(id=lid, **{kk: vv for kk, vv in e.items() if kk != 'placeholder'}))
            md['lg_name_original'] = md.get('lg_name')
            if md.get('ehak_code'):
                md.update(ehak_match='direct', ehak_successor=None, ehak_source=dict(table='Statistikaamet EHAK2026v1 (direct name match by ee_municipal_t1.py)', url=EHAK_26_URL))
            else:
                e = emap[(md.get('lg_name'), md.get('adopted'))]
                md.update(dict(ehak_successor=None), **e); md['ehak_source'] = ehak.source
            tb = len(t.encode('utf-8')); md['text_bytes'] = tb; md['text_bytes_before_strip'] = tb0; md['text_over_1mb'] = tb > MB1
            md['text_base64_run_chars'] = b64_chars(t); md['articles_base64_chars'] = sum(b64_chars(z['text']) for z in arts)
            agg['text_bytes_before'] += tb0; agg['text_bytes_after'] += tb
            if tb > maxt['bytes']: maxt = dict(bytes=tb, id=lid)
            if tb > MB1: big.append(dict(id=lid, lg=md.get('lg_name'), title=(law['title'] or '')[:100], text_bytes=tb, base64_run_chars=md['text_base64_run_chars'], status=law['law_status']))
            if md['text_base64_run_chars'] or md['articles_base64_chars']: b64.append(dict(id=lid, base64_run_chars=md['text_base64_run_chars'], articles_base64_chars=md['articles_base64_chars']))
            law['metadata_json'] = json.dumps(md, ensure_ascii=False)
            line = (json.dumps(dict(law=law, articles=arts), ensure_ascii=False) + '\n').encode('utf-8')
            if cur is None or cur['n'] >= SHARD_N or (cur['n'] and cur['ub'] + len(line) > SHARD_MAX):
                if cur: close(cur); k += 1
                cur = opn(k)
            assert len(line) <= SHARD_MAX, f'{lid} line > shard cap'
            cur['g'].write(line); cur['n'] += 1; cur['na'] += len(arts); cur['ne'] += not t.strip(); cur['nrep'] += law['law_status'] == 'repealed'; cur['ncan'] += md['is_canonical']
            cur['nfeed'] += feeds; cur['ub'] += len(line); cur['lgs'][md.get('lg_name')] += 1; cur['ids'].append(lid)
            agg['laws'] += 1; agg['articles'] += len(arts); agg[f"status:{law['law_status']}"] += 1; agg['canonical'] += md['is_canonical']; agg['feeds'] += feeds
            agg[f"ehak:{md['ehak_match']}"] += 1; agg['superseded_by_repeal_stub'] += lid in sup; agg['never_in_force'] += bool(md.get('never_in_force'))
            del r, law, md, t, arts, line
        if cur: close(cur)
        agg['ambiguous_groups'] = len(amb)
        strip = dict(blobs_removed=agg['blobs_removed'], blobs_in_articles=agg['blobs_in_articles'], decode_failed=agg['blob_decode_failed'], pdf_without_eof=agg['blob_pdf_no_eof'],
                     decoded_bytes=agg['blob_bytes_decoded'], base64_chars_removed=agg['blob_base64_chars'], text_bytes_before=agg['text_bytes_before'],
                     text_bytes_after=agg['text_bytes_after'], max_text_bytes_after=maxt, acts_over_1mb_after=len(big), titles_cleaned=agg['titles_cleaned'],
                     placeholder_format='[attachment: <name>, <mime>, <bytes>, <sha256>] (bytes and sha256 of the decoded file)')
        log('PASS2 done', dict(agg), 'rss', rss_mb(), 'mem', memavail())
        man = dict(format='jsonl.gz: one line per act {"law": {19 hub law cols}, "articles": [{9 cols}]}; fix fields live in law.metadata_json',
                   source=sman['source'], as_of_date=AS_OF, as_of_basis=AS_OF_BASIS, shards=shards, n_shards=len(shards), n_laws=agg['laws'], n_articles=agg['articles'],
                   complete=True, updated=now(), shard_caps=dict(max_acts=SHARD_N, max_unpacked_bytes=SHARD_MAX), parse=sman.get('parse'),
                   fix=dict(ts=ts, script='/workspace/scripts/ee_t1_fix.py', src_backup=src, src_manifest_sha256=bv['manifest_sha256'], as_of_date=AS_OF, as_of_basis=AS_OF_BASIS,
                            source_generated=SOURCE_GENERATED, source_generated_basis=SOURCE_GENERATED_BASIS, totals=dict(agg), strip=strip, ehak_source=ehak.source,
                            rules=__doc__.split('Fixes')[1].split('Memory guard')[0].strip()))
        atomic_json(f'{tmp}/manifest.json', man)
        v = verify(tmp, guard, expect_ids={x['id'] for x in rows}); log('VERIFY tmp', {kk: vv for kk, vv in v.items() if kk != 'stats'})
        if not v['ok']: raise RuntimeError(f"verify tmp failed {v['problems'][:5]}")
        if dry:
            log('DRY RUN done (no swap, no state change); output in', tmp, 'guard', guard.stats()); return tmp
        # ---- in-place swap (old shards are in the verified backup)
        guard.gate()
        new = set(shards)
        for n in os.listdir(SH):
            if n.startswith('ee_t1_kov_') and n.endswith('.jsonl.gz') and n not in new: os.remove(f'{SH}/{n}'); log('removed stale old shard', n)
        for n in sorted(new): os.replace(f'{tmp}/{n}', f'{SH}/{n}')
        os.replace(f'{tmp}/manifest.json', MAN); os.rmdir(tmp)
        v2 = verify(SH, guard, expect_ids={x['id'] for x in rows}); log('VERIFY in place', {kk: vv for kk, vv in v2.items() if kk != 'stats'})
        if not v2['ok']: raise RuntimeError(f"verify in place failed {v2['problems'][:5]}")
        msha = sha_file(MAN)
        # ---- decisions dump (for the review)
        mapped = collections.defaultdict(dict)
        for (lg, ad), e in emap.items():
            d = mapped[lg]; d.setdefault('acts', 0); d['acts'] += sum(1 for x in rows if x['lg'] == lg and x['adopted'] == ad and not x['ehak'])
            d.setdefault('results', {}); d['results'][e.get('ehak_successor') or 'null'] = {kk: e.get(kk) for kk in ('ehak_match', 'ehak_successor_name', 'ehak_successor_method', 'ehak_abolished_code',
                                                                                                                       'ehak_abolished_valid', 'ehak_unmapped_reason', 'ehak_successor_candidates', 'ehak_change_note')}
        sup_l = [dict(id=i, lg=rowmap[i]['lg'], no=rowmap[i]['no'], status=rowmap[i]['st_new'], valid_from=rowmap[i]['vf'], is_canonical=dec[i]['is_canonical'], **v) for i, v in sorted(sup.items())]
        dd = dict(ts=ts, as_of_date=AS_OF, manifest_sha256=msha, totals=dict(agg), strip=strip, status_source=dict(old_status), status_as_of=dict(new_status),
                  superseded_by_repeal_stub=sup_l, ambiguous_groups=amb, ehak_by_lg=mapped, articles_ids_suffixed=art_ids_fixed, acts_over_1mb=big, titles_cleaned=titles,
                  attachments=att_log, repeal_parse_problems=repeal_bad, base64_runs_left=b64, guard=guard.stats())
        atomic_json(f'{ROOT}/review/ee_t1_strip_decisions_{ts}.json', dd)
        st = json.load(open(f'{ROOT}/state.json'))
        st[STATE_KEY] = dict(status='T1_STRIP_SHARDS_DONE', started=st[STATE_KEY]['started'], done=now(), log=LOGF, src_backup=src, script='/workspace/scripts/ee_t1_fix.py',
                             manifest_sha256=msha, shards=len(shards), totals=dict(agg), strip=strip, as_of_date=AS_OF, decisions=f'{ROOT}/review/ee_t1_strip_decisions_{ts}.json',
                             verify=dict(tmp=v['ok'], in_place=v2['ok']), guard=guard.stats())
        st['ts'] = now(); atomic_json(f'{ROOT}/state.json', st)
        log('EE T1 FIX+STRIP DONE', 'manifest', msha, 'guard', guard.stats())
    except Stop as e:
        log('EE T1 FIX STOPPED CLEANLY (old shards untouched unless swap had started):', e, guard.stats())
        if not dry:
            st = json.load(open(f'{ROOT}/state.json')); st[STATE_KEY].update(status='T1_STRIP_STOPPED_MEM', stop=str(e), guard=guard.stats(), ended=now()); atomic_json(f'{ROOT}/state.json', st)
        if os.path.isdir(tmp): shutil.rmtree(tmp)
        sys.exit(3)
    finally: guard.alive = False
# ---------------- verify ----------------
def verify(d, guard, expect_ids=None):
    man = json.load(open(f'{d}/manifest.json')); bad = []; ids = []; art_ids = set(); n_art = 0; dup_art = 0
    canon = collections.defaultdict(list); vof = {}; members = collections.defaultdict(list); mx = dict(text_bytes=0, residual_b64=0)
    if man.get('as_of_date') != AS_OF: bad.append('manifest as_of_date')
    for name, s in sorted(man['shards'].items()):
        p = f'{d}/{name}'
        if not os.path.exists(p): bad.append(f'{name} missing'); continue
        if sha_file(p) != s['sha256']: bad.append(f'{name} sha256 mismatch')
        if s['n_laws'] > SHARD_N or s['unpacked_bytes'] > SHARD_MAX: bad.append(f'{name} over cap')
        c = 0; ub = 0
        with gzip.open(p, 'rb') as g:
            for l in g:
                guard.gate(); ub += len(l); r = json.loads(l); del l; law = r['law']; md = json.loads(law['metadata_json']); c += 1; ids.append(law['id'])
                if law['article_count'] != len(r['articles']): bad.append(f"{law['id']} article_count")
                if (law['law_status'] == 'repealed' or not md['is_canonical']) and r['articles']: bad.append(f"{law['id']} non-feeding act has articles")
                if md['feeds_articles'] != (md['is_canonical'] and law['law_status'] != 'repealed'): bad.append(f"{law['id']} feeds flag")
                if (law['text'] or '').startswith('Kehtetu') != (law['law_status'] == 'repealed'): bad.append(f"{law['id']} stub/status")
                if law['law_status'] == 'repealed' and not md.get('repeal_parse_ok'): bad.append(f"{law['id']} repeal not parsed")
                if not (law['text'] or '').strip(): bad.append(f"{law['id']} empty text")
                if md.get('as_of_date') != AS_OF or md.get('status_ref_date') != AS_OF: bad.append(f"{law['id']} as_of_date")
                vf, vte = md.get('valid_from'), md.get('valid_to_effective')
                if law['law_status'] == 'current' and not (vf and vf <= AS_OF and (not vte or vte >= AS_OF) and not md.get('never_in_force')): bad.append(f"{law['id']} current but not in force on as_of")
                if law['law_status'] != 'repealed' and law['law_status'] != status_as_of(dict(stub=False, vf=vf, vt=vte, never=md.get('never_in_force'))): bad.append(f"{law['id']} status != as_of rule")
                if md.get('in_force_as_of') and law['law_status'] not in ('current', 'repealed'): bad.append(f"{law['id']} in_force_as_of vs status")
                tb = len((law['text'] or '').encode('utf-8')); mx['text_bytes'] = max(mx['text_bytes'], tb)
                if tb > MB1: bad.append(f"{law['id']} text > 1 MB after strip")
                if TITLE_NOTE.match(law['title'] or ''): bad.append(f"{law['id']} title still carries a note")
                if len(md.get('attachments_stripped', [])) != md.get('attachments_stripped_n'): bad.append(f"{law['id']} attachments_stripped_n")
                for z in iter_str([law, md, r['articles'], [json.loads(a['metadata_json']) for a in r['articles']]]):
                    rb = residual_b64(z); mx['residual_b64'] = max(mx['residual_b64'], rb)
                    if rb > 1000: bad.append(f"{law['id']} base64-looking run of {rb} chars left")
                members[md['version_group_key']].append(law['id'])
                if md['is_canonical']: canon[md['version_group_key']].append(law['id'])
                else: vof[law['id']] = (md['version_of'], md['version_group_key'])
                for a in r['articles']:
                    n_art += 1
                    if a['id'] in art_ids: dup_art += 1
                    art_ids.add(a['id'])
                del r, law, md
        if c != s['n_laws']: bad.append(f'{name} {c} lines != {s["n_laws"]}')
        if ub != s['unpacked_bytes']: bad.append(f'{name} unpacked bytes mismatch')
    if len(set(ids)) != len(ids): bad.append('duplicate law ids')
    if expect_ids is not None and set(ids) != expect_ids: bad.append('law id set differs from source')
    for k, v in members.items():
        if len(canon.get(k, [])) != 1: bad.append(f'group {k} has {len(canon.get(k, []))} canonical')
    for i, (c, k) in vof.items():
        if canon.get(k, [None])[0] != c: bad.append(f'{i} version_of {c} is not the canonical of its group')
    if dup_art: bad.append(f'{dup_art} duplicate article ids')
    if n_art != man['n_articles']: bad.append('article total != manifest')
    return dict(ok=not bad, laws=len(ids), shards=len(man['shards']), articles=n_art, article_ids_unique=dup_art == 0, groups=len(members),
                max_text_bytes=mx['text_bytes'], max_residual_base64_run=mx['residual_b64'], problems=bad[:50])
if __name__ == '__main__':
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(1)
    if a[0] == 'backup': backup()
    elif a[0] in ('run', 'dryrun'): run(a[a.index('--src') + 1] if '--src' in a else latest_backup(), dry=a[0] == 'dryrun')
    elif a[0] == 'verify':
        g = Guard(); r = verify(SH, g); g.alive = False; r['guard'] = g.stats(); print(json.dumps(r, indent=1, ensure_ascii=False)); sys.exit(0 if r['ok'] else 1)
    else: print(__doc__); sys.exit(1)
