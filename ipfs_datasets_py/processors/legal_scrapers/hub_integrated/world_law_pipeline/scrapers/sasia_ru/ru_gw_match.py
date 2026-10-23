"""Strict Gosweb host->place matcher. Requires: whole-word name stem in site header/logo/footer (not generic title),
matching level word, region code (metricRegion / -rNN host suffix / leading digits) consistent with the place's OKTMO/OKATO region,
and a unique candidate. Output: _ru/gw_matches.jsonl (status ok|ambig|nomatch|region_mismatch|...)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,re,collections
D=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/')
OK2SUB={'01':'22','03':'23','04':'24','05':'25','07':'26','08':'27','10':'28','11':'29','12':'30','14':'31','15':'32','17':'33','18':'34','19':'35','20':'36','22':'52','24':'37','25':'38','26':'06','27':'39','28':'69','29':'40','30':'41','32':'42','33':'43','34':'44','35':'91','36':'63','37':'45','38':'46','40':'78','41':'47','42':'48','44':'49','45':'77','46':'50','47':'51','49':'53','50':'54','52':'55','53':'56','54':'57','56':'58','57':'59','58':'60','60':'61','61':'62','63':'64','64':'65','65':'66','66':'67','67':'92','68':'68','69':'70','70':'71','71':'72','73':'73','75':'74','76':'75','77':'87','78':'76','79':'01','80':'02','81':'03','82':'05','83':'07','84':'04','85':'08','86':'10','87':'11','88':'12','89':'13','90':'15','91':'09','92':'16','93':'17','94':'18','95':'19','96':'20','97':'21','98':'14','99':'79'}
LEVELS=[('rural_settlement',r'сельск\w*\s+поселени|сельсовет|сельского\s+округа'),('urban_settlement',r'городск\w*\s+поселени'),('urban_okrug',r'городск\w*\s+округ|город\w*\s+округ'),('municipal_okrug',r'муниципальн\w*\s+округ'),('district',r'муниципальн\w*\s+район|\bрайон\w*'),('settlement_unit',r'сельск\w*\s+муниципальн\w*\s+образовани|\bсело\b|\bпос[её]лок|\bдеревн'),('city',r'\bгород\w*\b|\bмэри')]
REG=re.compile(r'[а-я\-]+(ской|ского|ий|ая)\s+(област\w*|кра[яей]\w*|автономн\w*\s+округ\w*)|республик\w*\s+[а-я\-]+(\s+[а-я\-]+)?|\b(ск|рм|рб|рт|кбр|кчр|хмао|янао|ло|мо)\b')
COMPAT={'city':{'urban_okrug','urban_settlement','city'}}
def compat(a,b):
    A=set(a)|set().union(*[COMPAT.get(x,set()) for x in a]); B=set(b)|set().union(*[COMPAT.get(x,set()) for x in b])
    return bool(set(a)&B or set(b)&A)
def level_of(s):
    s=s.lower(); return [k for k,p in LEVELS if re.search(p,s)]
GEN={'городской','округ','город','поселение','сельское','городское','муниципальный','район','муниципальное','образование','муниципального','образования','округа','района','поселения','сельский','совет','сельсовет','рабочий','посёлок','поселок','село','деревня','станица','хутор','аул','закрытое','административно-территориальное','внутригородское','территория','—','-','«','»','"'}
def name_words(label):
    ws=[w.strip('«»"()., ') for w in re.split(r'[\s]+',label or '')]
    return [w for w in ws if w and w.lower() not in GEN and len(w)>=3]
def stem(w):
    w=w.lower().replace('ё','е')
    for suf in ('ского','скому','ский','ская','ское','ской','цкого','цкий','цкое','ого','ий','ая','ое','ой','ый','а','я','о','ы','и','ь'):
        if w.endswith(suf) and len(w)-len(suf)>=4: return w[:-len(suf)]
    return w
def region_codes(p):
    cs=set()
    for c in (p.get('oktmo') or [])+(p.get('okato') or []):
        if isinstance(c,str) and len(c)>=2:
            cs.add(c[:2]); cs.add(OK2SUB.get(c[:2],''))
            if c[:3]=='718': cs.add('86')
            if c[:3]=='719': cs.add('89')
            if c[:3]=='111': cs.add('83')
    return {c.lstrip('0') for c in cs if c}
wd={json.loads(l)['qid']:json.loads(l) for l in open(D+'wd_ru.jsonl')}
idx=collections.defaultdict(list)
for q,p in wd.items():
    for w in name_words(p.get('ru'))[:2]:
        idx[stem(w)].append(p)
known={json.loads(l)['host']:json.loads(l)['place_id'] for l in open(D+'gosweb_hosts.jsonl')}
out=open(D+'gw_matches.jsonl','w'); cnt=collections.Counter()
for l in open(D+'gw_headers.jsonl'):
    h=json.loads(l)
    if h.get('err') or h.get('status')!=200: cnt['unreachable']+=1; continue
    logo=' '.join(h.get('logo_alt',[])).lower().replace('ё','е')
    spec=[w for w in re.findall(r'[а-я\-]{4,}',REG.sub(' ',logo)) if w not in GEN and not re.match(r'администрац|официальн|сайт|муниципальн|образовани|главн|страниц|городск|сельск|поселени|округ|район',w)]
    txt=logo if spec else (h.get('header','') or h.get('header_top','')).lower().replace('ё','е')
    txt=REG.sub(' ',txt)
    if re.search(r'школ|сош|детск|гимнази|лице|колледж|больниц|библиотек|музе|учреждени|дом культуры|центр\b|мбу|мку|моу|мбоу|гбу|гку',txt): r={'status':'not_omsu'}
    else:
        codes=set()
        m=re.search(r'-r(\d+)',h['host']); codes|={m.group(1).lstrip('0')} if m else set()
        m=re.match(r'^(\d{2})[a-z]',h['host']); codes|={m.group(1).lstrip('0')} if m else set()
        m=re.search(r'(\d{2})\.gosuslugi',h['host']); codes|={m.group(1).lstrip('0')} if m else set()
        if h.get('region'): codes.add(h['region'].lstrip('0'))
        words=set(re.findall(r'[а-я\-]{4,}',txt)); lv=level_of(txt)
        cands={}
        for w in words:
            for p in idx.get(stem(w),[]):
                nw=name_words(p.get('ru'))
                if not nw or not all(re.search(r'\b'+re.escape(stem(x))+r'[а-я]*\b',txt) for x in nw): continue
                pl=level_of(p.get('ru') or '')
                if not lv or not pl or not compat(lv,pl): continue
                if codes and not (region_codes(p)&codes): continue
                cands[p['qid']]=p
        if len(cands)==1:
            p=list(cands.values())[0]; r={'status':'ok','place_id':'wd:'+p['qid'],'place_ru':p['ru'],'codes':sorted(codes),'levels':lv}
        else: r={'status':'ambig' if cands else 'nomatch','n':len(cands),'cands':[c['ru'] for c in list(cands.values())[:4]],'codes':sorted(codes)}
    r.update(host=h['host'],site=(h.get('logo_alt') or [h.get('header_top','')[:120]])[0],known=known.get(h['host']))
    cnt[r['status']]+=1; out.write(json.dumps(r,ensure_ascii=False)+'\n')
print(cnt)
