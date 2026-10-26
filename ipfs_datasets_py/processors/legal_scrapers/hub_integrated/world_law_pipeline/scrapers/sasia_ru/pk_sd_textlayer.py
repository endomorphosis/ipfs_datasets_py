# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,os,re,sys,time,subprocess,datetime,requests
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from pk_sd_title import title as mk_title
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
from schema import validate_record,validate_file
B=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging'); LST=B+'/pdf/_state/text_layer_pk_sd.jsonl'
RAW=B+'/sasia_ru/_raw/pk_sd'; LOC=B+'/pdf/PK/iso_PK-SD'; OUT=B+'/sasia_ru/PK'
DONE=B+'/sasia_ru/_ocr/pk_sd_done.jsonl'; LOW=B+'/sasia_ru/_ocr/pk_sd_lowtext.jsonl'
S=requests.Session(); S.headers['User-Agent']='world-law-research-bot/1.0 (municipal law archive)'
MAXFAIL=3
FAILS=B+'/sasia_ru/_ocr/pk_sd_failcount.json'; DEF=B+'/sasia_ru/_ocr/pk_sd_deferred.jsonl'
def deferred():
    if not os.path.exists(DEF): return set()
    now=datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {r['doc_id'] for r in map(json.loads,open(DEF)) if r.get('retry_after','9')>now or r.get('retries',0)>=MAXFAIL}
def fail(x,err):
    fc=json.load(open(FAILS)) if os.path.exists(FAILS) else {}
    fc[x['doc_id']]=fc.get(x['doc_id'],0)+1; json.dump(fc,open(FAILS,'w'))
    if fc[x['doc_id']]>=MAXFAIL:
        ra=(datetime.datetime.now(datetime.UTC)+datetime.timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
        st='failed_ssl' if 'rc 35' in err else 'failed'
        with open(DEF,'a') as f: f.write(json.dumps({**x,'status':st,'error':err,'retries':fc[x['doc_id']],'retry_after':ra})+'\n')
def done():
    return {json.loads(l)['doc_id'] for l in open(DONE)} if os.path.exists(DONE) else set()
def stage(recs):
    ts=datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')
    fin=f'{OUT}/iso_PK-SD.pdftext{ts}.jsonl'; tmp=f'{OUT}/.tmp.iso_PK-SD.pdftext{ts}.jsonl'
    with open(tmp,'w') as f:
        for r in recs: f.write(json.dumps(r,ensure_ascii=False)+'\n')
        f.flush(); os.fsync(f.fileno())
    v=validate_file(tmp,expect_place_key='iso_PK-SD') if 'expect_place_key' in validate_file.__code__.co_varnames else validate_file(tmp)
    print('validate',fin,{k:v[k] for k in ('ok','rows','bad_rows')},flush=True)
    if not v.get('ok') or v.get('bad_rows') or v.get('file_errors'): os.remove(tmp); raise SystemExit(f'validation failed {v}')
    os.rename(tmp,fin)
MC=RAW+'/meta.jsonl'
META={json.loads(l)['doc_id']:json.loads(l) for l in open(MC)} if os.path.exists(MC) else {}
import html as H
def meta(x):
    d=x['doc_id']
    if d in META: return META[d]
    time.sleep(3); s=subprocess.run(['curl','-sf','-m','120','-A',S.headers['User-Agent'],x['source_url']],capture_output=True,text=True).stdout
    if not s: raise Exception('meta fetch failed')
    g=lambda k:(lambda m:H.unescape(re.sub(r'\s+',' ',m.group(1))).strip() if m else None)(re.search(r'id="ContentPlaceHolder1_lbl'+k+r'"[^>]*>([^<]*)',s))
    m={'doc_id':d,'title':g('Title'),'no':g('DocumentNo'),'date':g('DocumentDate'),'lang':g('Language')}
    open(MC,'a').write(json.dumps(m)+'\n'); META[d]=m; return m
def iso(d):
    try: return datetime.datetime.strptime(d,'%d-%b-%Y').strftime('%Y-%m-%d')
    except Exception: return None
idle=0
while idle<6:
    D=done(); L=[json.loads(l) for l in open(LST) if l.strip()]
    DF=deferred(); todo=[x for x in L if x['doc_id'] not in D and x['doc_id'] not in DF]
    if not todo:
        if DF: print('only deferred IDs remain; exiting',len(DF),flush=True); break
        idle+=1; time.sleep(600); continue
    idle=0; recs=[]; sts=[]
    for x in todo[:50]:
        did=x['doc_id']; p=f'{LOC}/{did}.pdf'; via='local'
        if not os.path.exists(p):
            p=f'{RAW}/{did}.pdf'; via='live'
            if not os.path.exists(p):
                time.sleep(3)
                try:
                    tp=p+'.part'
                    rc=subprocess.run(['curl','-sf','-m','240','-A',S.headers['User-Agent'],'-o',tp,x['pdf_url']]).returncode
                    if rc or not open(tp,'rb').read(4)==b'%PDF': raise Exception(f'curl rc {rc}')
                    os.rename(tp,p)
                except Exception as e:
                    print('ERR',did,e,flush=True); fail(x,str(e)); time.sleep(30); continue
        try: t=subprocess.run(['pdftotext','-layout',p,'-'],capture_output=True,text=True,timeout=300).stdout
        except subprocess.TimeoutExpired:
            print('TIMEOUT',did,flush=True); t=''
        t=re.sub(r'[ \t]+\n','\n',t).strip(); n=len(re.sub(r'\s','',t))
        st={'doc_id':did,'chars':n,'via':via}
        if n<200:
            open(LOW,'a').write(json.dumps({**x,'pdftotext_chars':n,'country':'PK','place_key':'iso_PK-SD','language':'en','source':'sindhlaws'})+'\n'); st['ocr']=True
        else:
            try: m=meta(x)
            except Exception as e: print('METAERR',did,e,flush=True); m={}
            title=(m.get('title') or '').rstrip('.').strip() or mk_title(t)
            dt='regulation' if re.search(r'\b(rules|regulations?|order|notification)\b',title,re.I) and not re.search(r'\b(act|ordinance)\b',title,re.I) else 'statute'
            rec={'place_id':'iso:PK-SD','country_code':'PK','doc_id':did,'source_platform':'sindhlaws','source_url':x['source_url'],
                 'original_url':x['pdf_url'],'doc_type':dt,'adopted_date':iso(m.get('date')),'title_source':'sindhlaws_page' if m.get('title') else 'pdf_heuristic','language':'en','content_format':'pdf_text','consolidated':False,
                 'title_native':title,'number':m.get('no') or did.replace('sindhlaws-',''),'text':t,
                 'retrieved_at':datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),'source_official':True,
                 'source_org':'Government of Sindh','source_policy':'robots_allowed_rfc9309','place_name':'Sindh','iso_3166_2':'PK-SD','admin_level':'adm1'}
            e=validate_record(rec)
            if e: print('INVALID',did,e,flush=True); continue
            recs.append(rec)
        sts.append(st)
    if recs: stage(recs)
    with open(DONE,'a') as f:
        for st in sts: f.write(json.dumps(st)+'\n')
print('exit idle',flush=True)
