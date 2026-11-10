"""Standard pre-HUB-READY scan + redaction (v2, 2026-10-24). Patterns are RE2 (pyarrow.compute)."""
BATCH=2000  # rows per batch for scan3/redact3/scan5/scan7 (stage sets lower for big-text tables)
import pyarrow as pa, pyarrow.compute as pc, pyarrow.parquet as pq, re, os, json
def _root():
  import os
  return os.environ.get('Q4_BUNDLE_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CRED=open(os.path.join(_root(),'vendor','credential_shapes_regex.txt'),encoding='utf-8').read().strip()
WEBDOM=r'(?:googlemail|protonmail|rediffmail|hotmail|hotmial|hotmal|homail|outlook|outlok|gmaill|gmail|gmial|gamil|gmal|gmai|yahooo|yahoo|yaho|ymail|icloud|yandex|proton|mail\.ru|live|msn|aol|gmx|qq|163|126)'
# webmail incl. typo-domain, spaced ("x @ gmail . com"), [at]/(at) and truncated ("x@gmai") forms
WEBMAIL=r'(?i)[A-Za-z0-9._%+-]+\s?(?:@|＠|\[at\]|\(at\))\s?'+WEBDOM+r'\b(?:\s?\.\s?[A-Za-z]{2,6}){0,2}'
COSWEB=r'(?i)[A-Za-z0-9._%+-]+@(gmail|googlemail|gmial|gmai|gamil|yahoo|yaho|ymail|outlook|hotmail|hotmial|live|msn|aol|proton|protonmail|icloud|mail\.ru|yandex|gmx|qq|163|126|rediffmail)\.'
PATH=r'(?:/home/|/Users/|[A-Za-z]:\\\\Users\\\\)[A-Za-z0-9_.-]+(?:[/\\\\][A-Za-z0-9_.-]+)*'
TOKEN=r'hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-*|[?&](?:sig|sv)=[A-Za-z0-9%]{8,}'
REDACT=[('email',WEBMAIL,'[REDACTED-EMAIL]'),('path',PATH,'[REDACTED-PATH]'),('secret',TOKEN,'[REDACTED-SECRET]')]
NATID={  # report-only national-ID shapes (context-anchored to limit false positives on law numbers)
 'CI_BO':r'(?i)\b(?:C\.\s?[Il]\.|C\.\s?I\b|CI|c[ée]dula\s+de\s+identidad)\s*(?:N[°º.o]\.?\s*)?:?\s*(?:\d{1,3}(?:\.\d{3}){2}|\d{5,9})(?:\s?-\s?\d[A-Z]?)?\s?(?:L\.?P\.?|CBBA|Cbba|S\.?C\.?|OR|PT|CH|TJ|BE|PD)?\b',
 'DNI':r'(?i)\bD\.?\s?N\.?\s?I\.?\s*(?:N[°º.o]\.?\s*)?:?\s*(?:\d{1,3}(?:\.\d{3}){2}|\d{7,8})(?:\s?-?\s?[A-Z])?\b',
 'CPF':r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b',
 'CPR':r'(?i)\bCPR(?:-?nr\.?)?\s*:?\s*\d{6}-?\d{4}\b',
 'CURP':r'\b[A-Z]{4}\d{6}[HM][A-Z]{5}[0-9A-Z]\d\b',
 'SSN':r'(?i)\b(?:SSN|social security(?: number)?)\D{0,6}\d{3}-\d{2}-\d{4}\b',
 'NIE_NIF':r'(?i)\b(?:NIE|NIF)\s*:?\s*[XYZ]?\d{7,8}[A-Z]\b'}
CHECKS={'credential_shapes':CRED,'webmail_cos':COSWEB,'webmail_ext':WEBMAIL,'path':PATH,'token':TOKEN}
def _strcols(b): return [(i,f.name) for i,f in enumerate(b.schema) if pa.types.is_string(f.type) or pa.types.is_large_string(f.type)]
def scan(path,samples=3):
  pf=pq.ParquetFile(path);h={k:0 for k in list(CHECKS)+['natid_'+k for k in NATID]};S={};off=0
  for b in pf.iter_batches(batch_size=BATCH):
    for i,n in _strcols(b):
      c=b.column(i).cast(pa.string())
      for k,r in list(CHECKS.items())+[('natid_'+k,v) for k,v in NATID.items()]:
        m=pc.match_substring_regex(c,r);x=pc.sum(m).as_py() or 0
        if x:
          h[k]+=x
          if k.startswith('natid_') and len(S.setdefault(k,[]))<samples:
            for j in pc.indices_nonzero(m).to_pylist()[:samples]:
              s=c[j].as_py();mo=re.search(NATID[k[6:]],s);ex=mo.group(0) if mo else ''
              S[k].append({'row':off+j,'column':n,'match_masked':re.sub(r'\d(?=\d{2})','#',ex)})
    off+=b.num_rows
  return h,S
def v_strip(r): return r[4:] if r.startswith('(?i)') else r
def redact(src,dst):
  pf=pq.ParquetFile(src);sch=pf.schema_arrow;w=pq.ParquetWriter(dst,sch,compression='zstd');locs=[];off=0;n=0
  for b in pf.iter_batches(batch_size=BATCH):
    cols=list(b.columns)
    for i,name in _strcols(b):
      c=cols[i]
      for kind,r,mark in REDACT:
        cnt=pc.count_substring_regex(c.cast(pa.string()),r)
        for j in pc.indices_nonzero(pc.fill_null(cnt,0)).to_pylist():
          locs.append({'row':off+j,'column':name,'kind':kind,'count':cnt[j].as_py(),'marker':mark})
        c=pc.replace_substring_regex(c,r,mark)
      cols[i]=c.cast(sch.field(name).type)
    w.write_table(pa.Table.from_batches([pa.RecordBatch.from_arrays(cols,schema=sch)]));off+=b.num_rows
  w.close();assert pq.read_metadata(dst).num_rows==pf.metadata.num_rows==off
  return locs,off

# ---- v3: bundled scan6 (relative) ----
from scan6 import PAT as P6, FAILK as _FAILK
FAILK=set(_FAILK)
DOM3=r"(?:g\s*m\s*a\s*i\s*l|gmial|gmai|gamil|gnail|gmaill|gmal|googlemail|yahoo(?:\s?\.\s?[a-z.]+)?|yaho|yahooo|ymail|rocketmail|outlook|outlok|hotmail|hotmial|hotmal|homail|live|msn|aol|proton(?:mail)?|pm\s?\.\s?me|icloud|me\s?\.\s?com|(?:mail|masil|maill|mial|mali|maii|rnail)\s?\.\s?ru|inbox\s?\.\s?ru|list\s?\.\s?ru|bk\s?\.\s?ru|internet\s?\.\s?ru|yandex(?:\s?\.\s?[a-z]+)?|ya\s?\.\s?ru|rambler|gmx(?:\s?\.\s?[a-z]+)?|web\s?\.\s?de|t-online|freenet|qq|163|126|yeah\s?\.\s?net|sina|sohu|rediffmail|zoho|mail\s?\.\s?com|email\s?\.\s?com|usa\s?\.\s?com|tutanota|tuta\s?\.\s?io|libero|virgilio|laposte|orange\s?\.\s?fr|wanadoo|free\s?\.\s?fr|sfr\s?\.\s?fr|terra|uol|bol\s?\.\s?com\s?\.\s?br|seznam|centrum\s?\.\s?cz|wp\s?\.\s?pl|o2\s?\.\s?pl|onet|interia|abv\s?\.\s?bg|ukr\s?\.\s?net|i\s?\.\s?ua|meta\s?\.\s?ua|naver|daum|hanmail|nate|yahoo\s?\.\s?co\s?\.\s?jp|excite|lycos|mail\s?\.\s?az|box\s?\.\s?az|rocket\s?\.\s?az)"
WEB3=re.compile(r"(?i)[A-Za-z0-9._%+-]+\s*(?:@|\(at\)|\[at\]|\{at\}|＠|\sat\s)\s*"+DOM3+r"(?![A-Za-z0-9-])(?:\s?\.\s?[A-Za-z]{2,6}(?![A-Za-z0-9-])){0,2}")
# v4 (2026-10-24 23:2x PT): dotless/OCR-tolerant free-webmail ("@gmailcom", "@gmail ,com", country TLDs)
FREEDOM=r"(?:gmail|hotmail|yahoo|outlook|live|protonmail|icloud|msn|aol|ymail|googlemail|terra|bol|uol|libero|gmx|web|orange|free|laposte|wanadoo|yandex|mail)"
WEB5=re.compile(r"(?i)(?<![A-Za-z0-9._%+@-])[A-Za-z0-9._%+-]+?(?:\s?(?:\(a|[@QGaeé2YB8“\"'’”(])??\s?|\s[A-Za-z0-9]\s)(?:gmail|hotmail|yahoo|outlook|msn|aol|icloud|proton(?:mail)?|ymail|(?<=G[Op])mail)(?:\s?[.,]\s?(?:com|net|ru|br|es|ar|mx|fr|it|de|co|bo)|\s?com)(?![A-Za-z0-9])")  # restage11 mangled/missing-@ webmail
WEB4=re.compile(r"(?i)[A-Za-z0-9][A-Za-z0-9._%+-]*\s?@\s?"+FREEDOM+r"\s?[.,]?\s?(?:com(?:\s?[.,]\s?(?:br|ar|mx|co|pe|bo|uy|py|ec|ve|cl|es|au))?|co\s?[.,]\s?uk|es|fr|it|de|net|org|ru|bo|ar|br|mx|cl|pe|uk)(?![A-Za-z0-9])")
PATHX=re.compile(r"^/workspace/legal-corpora/")   # CoS-accepted build path in json_path
def _exempt(k,col,val,mo): return k in('path','secret') and col=='json_path' and PATHX.match(val) is not None and mo.start()==0
def scan3(path,samples=20):
  f=pq.ParquetFile(path);P=dict(P6);P['webmail3']=WEB3;P['webmail4']=WEB4;P['webmail5']=WEB5;h={k:0 for k in P};h['path_exempt_json_path']=0;S={};base=0
  for b in f.iter_batches(batch_size=BATCH):
    for name in b.schema.names:
      c=b.column(name)
      if not (pa.types.is_string(c.type) or pa.types.is_large_string(c.type)): continue
      for i,v in enumerate(c.to_pylist()):
        if not v: continue
        for k,r in P.items():
          for mo in r.finditer(v):
            if _exempt(k,name,v,mo): h['path_exempt_json_path']+=(k=='path');continue
            h[k]+=1
            if len(S.setdefault(k,[]))<samples: S[k].append({'row':base+i,'col':name,'ctx':re.sub(r'\d','#',v[max(0,mo.start()-40):mo.end()+20])})
    base+=b.num_rows
  fail={k:h[k] for k in list(FAILK)+['webmail3','webmail4','webmail5'] if h.get(k)}
  return h,S,fail
def redact3(src,dst):
  """email(webmail3+scan6 webmail+SEC email shapes)->[REDACTED-EMAIL], path->[REDACTED-PATH], token->[REDACTED-SECRET]; every string cell of every column; json_path legal-corpora exempt"""
  pf=pq.ParquetFile(src);sch=pf.schema_arrow;w=pq.ParquetWriter(dst,sch,compression='zstd');locs=[];base=0
  R=[('email',WEB5,'[REDACTED-EMAIL]'),('email',WEB4,'[REDACTED-EMAIL]'),('email',WEB3,'[REDACTED-EMAIL]'),('email',P6['webmail'],'[REDACTED-EMAIL]'),('path',P6['path'],'[REDACTED-PATH]'),('secret',P6['secret'],None)]
  for b in pf.iter_batches(batch_size=BATCH):
    cols=[]
    for name in b.schema.names:
      c=b.column(name)
      if not (pa.types.is_string(c.type) or pa.types.is_large_string(c.type)): cols.append(c);continue
      vals=c.to_pylist();ch=False
      for i,v in enumerate(vals):
        if not v: continue
        for kind,r,mark in R:
          n=[0]
          def sub(mo,kind=kind,mark=mark):
            if _exempt('path',name,v,mo): return mo.group(0)
            g=mo.group(0);n[0]+=1
            if mark: return mark
            return '[REDACTED-EMAIL]' if '@' in g else ('[REDACTED-PATH]' if g.startswith('/') else '[REDACTED-SECRET]')
          v2=r.sub(sub,v)
          if n[0]: locs.append({'row':base+i,'column':name,'kind':kind,'count':n[0],'marker':mark or ('[REDACTED-EMAIL]' if kind=='email' else '[REDACTED-SECRET]')});v=v2;ch=True
        vals[i]=v
      cols.append(pa.array(vals,type=c.type) if ch else c)
    w.write_table(pa.Table.from_arrays(cols,schema=sch));base+=b.num_rows
  w.close();assert pq.read_metadata(dst).num_rows==base==pf.metadata.num_rows
  return locs,base
# v5 (2026-10-25 PT): widened free-webmail: glued/dotless ("JOHNGMAILCOM", "john.gmailcom"), junk-in-place-of-@,
# spaced ("john gmail . com" only with a junk char or glued), and host-first ("gmail.com@john", "gmail.com: john").
HOST6=r"(?:gmail|googlemail|hotmail|yahoo|outlook|icloud|protonmail|ymail|yandex|gmx)"
WEB6=re.compile(r"(?i)(?:(?<![A-Za-z0-9._%+@-])[A-Za-z0-9._%+-]{2,}(?:[^\sA-Za-z0-9\]]\s?|\s[^\sA-Za-z0-9\]]\s?)?"+HOST6+r"\s?[.,]?\s?com(?:\s?[.,]\s?[a-z]{2})?(?![A-Za-z0-9])"
                r"|(?<![A-Za-z0-9._%+@-])[A-Za-z0-9._%+-]{2,}\s"+HOST6+r"com(?![A-Za-z0-9])"
                r"|\b"+HOST6+r"\s?[.,]\s?com\s?[@:/|]\s?[A-Za-z0-9._%+-]{2,})")
def scan4(path,samples=0):
  h,S,fail=scan3(path,samples=samples);n=0
  f=pq.ParquetFile(path)
  for b in f.iter_batches(batch_size=BATCH):
    for name in b.schema.names:
      c=b.column(name)
      if not (pa.types.is_string(c.type) or pa.types.is_large_string(c.type)): continue
      for v in c.to_pylist():
        if v: n+=len(WEB6.findall(v))
  h['webmail6']=n
  if n: fail['webmail6']=n
  return h,fail
def scan_text4(t):
  P=dict(P6);P['webmail3']=WEB3;P['webmail4']=WEB4;P['webmail5']=WEB5;P['webmail6']=WEB6
  h={k:len(r.findall(t)) for k,r in P.items()}
  return h,{k:h[k] for k in list(FAILK)+['webmail3','webmail4','webmail5','webmail6'] if h.get(k)}
def redact4(src,dst):
  """WEB6 pass (whole match incl. local part -> [REDACTED-EMAIL]) then redact3 semantics."""
  import tempfile
  pf=pq.ParquetFile(src);sch=pf.schema_arrow;tmp=dst+'.web6.tmp';w=pq.ParquetWriter(tmp,sch,compression='zstd');locs=[];base=0
  for b in pf.iter_batches(batch_size=BATCH):
    cols=[]
    for name in b.schema.names:
      c=b.column(name)
      if not (pa.types.is_string(c.type) or pa.types.is_large_string(c.type)): cols.append(c);continue
      vals=c.to_pylist();ch=False
      for i,v in enumerate(vals):
        if not v: continue
        v2,k=WEB6.subn('[REDACTED-EMAIL]',v)
        if k: locs.append({'row':base+i,'column':name,'kind':'email','count':k,'marker':'[REDACTED-EMAIL]'});vals[i]=v2;ch=True
      cols.append(pa.array(vals,type=c.type) if ch else c)
    w.write_table(pa.Table.from_arrays(cols,schema=sch));base+=b.num_rows
  w.close();l2,n=redact3(tmp,dst);os.remove(tmp)
  assert n==base==pf.metadata.num_rows
  return locs+l2,n
# v5-fast (2026-10-25 PT): same fail-key regexes, RE2 prefilter (pyarrow) selects candidate cells first.
PRE=r"(?i)(?:"+DOM3+r"|mail|@|＠|/home/|/users/|/workspace/|/root/|:\\\\?users)"
def scan5(path):
  import pyarrow.compute as pc
  P={'webmail':P6['webmail'],'path':P6['path'],'secret':P6['secret'],'webmail3':WEB3,'webmail4':WEB4,'webmail5':WEB5,'webmail6':WEB6}
  h={k:0 for k in P};f=pq.ParquetFile(path)
  for b in f.iter_batches(batch_size=BATCH):
    for name in b.schema.names:
      c=b.column(name)
      if not (pa.types.is_string(c.type) or pa.types.is_large_string(c.type)): continue
      c=c.cast(pa.string());m=pc.or_(pc.fill_null(pc.match_substring_regex(c,PRE),False),pc.fill_null(pc.match_substring_regex(c,CRED),False))
      for j in pc.indices_nonzero(m).to_pylist():
        v=c[j].as_py()
        for k,r in P.items():
          for mo in r.finditer(v):
            if _exempt(k,name,v,mo): continue
            if k=='path' and name=='json_path' and mo.group(0)=='/workspace/' and v.startswith('/workspace/legal-corpora/'): continue
            h[k]+=1
  return h
# v6 (2026-10-25 PT): false-positive-tolerant hit LOG (redaction of real addresses unchanged).
# A hit is FP only by a generic rule below or a CoS-verified allowlist entry (sha256 of matched string; no raw text stored).
import hashlib as _hl
ALLOWF=os.path.join(_root(),'vendor','webmail_fp_allowlist.json')
def _allow():
  try:
    raw=json.load(open(ALLOWF))
  except Exception:
    return {}
  if isinstance(raw, dict):
    return raw
  if isinstance(raw, list):
    out={}
    for e in raw:
      if isinstance(e, dict) and e.get('sha256'):
        out[e['sha256']]=e.get('reason','allowlist')
    return out
  return {}

def fp_reason(v,mo):
  g=mo.group(0);a=v[max(0,mo.start()-12):mo.start()];z=v[mo.end():mo.end()+2]
  if re.search(r'https?://\S*$|www\.\S*$',a) or z.startswith('/') or re.search(r'(?i)groups\.yahoo',g): return 'url'
  if re.search(r"[‘'\"“]\s*(?:gmail|yahoo|hotmail|outlook)",g,re.I) and '@' not in g: return 'quoted_domain_example'
  if re.search(r'(?i)\s(?:outlook|live|aol|msn)\s?[.,]\s?[a-z]{2,3}$',g) and '@' not in g: return 'word_then_punct'
  if re.search(r'(?:[A-Z]{2,}-)+[A-Z]*AOL\b|-PAOL',g): return 'acronym_aol'
  h=_hl.sha256(g.encode()).hexdigest();A=_allow()
  if h in A: return 'allowlist:'+A[h]
  return None
def scan7(path):
  import pyarrow.compute as pc
  P={'webmail':P6['webmail'],'path':P6['path'],'secret':P6['secret'],'webmail3':WEB3,'webmail4':WEB4,'webmail5':WEB5,'webmail6':WEB6}
  real={k:0 for k in P};fp={};f=pq.ParquetFile(path)
  for b in f.iter_batches(batch_size=BATCH):
    for name in b.schema.names:
      c=b.column(name)
      if not (pa.types.is_string(c.type) or pa.types.is_large_string(c.type)): continue
      c=c.cast(pa.string());m=pc.or_(pc.fill_null(pc.match_substring_regex(c,PRE),False),pc.fill_null(pc.match_substring_regex(c,CRED),False))
      for j in pc.indices_nonzero(m).to_pylist():
        v=c[j].as_py()
        for k,r in P.items():
          for mo in r.finditer(v):
            if _exempt(k,name,v,mo): continue
            if k=='path' and name=='json_path' and mo.group(0)=='/workspace/' and v.startswith('/workspace/legal-corpora/'): continue
            why=fp_reason(v,mo) if k.startswith('webmail') else None
            if why: fp[why]=fp.get(why,0)+1
            else: real[k]+=1
  return real,fp
