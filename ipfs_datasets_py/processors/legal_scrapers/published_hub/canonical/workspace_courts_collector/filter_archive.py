import json,glob,re,subprocess,hashlib,collections,os,zipfile
from bs4 import BeautifulSoup
B='/workspace/courts'; A=f'{B}/staging/state_rules_archive'; RV=f'{B}/review_state_rules_archive'
CUE=re.compile(r'\b(?:Rule|RULE|Rules|§|Section|SECTION|Sec\.)\s*\d+[A-Za-z]?(?:[.\-:]\d+)*')
SUB=re.compile(r'(?m)^\s*\((?:[a-z]|\d{1,2}|[ivx]{1,4})\)\s')
TITLE=re.compile(r'(?i)\b(rules? of|court rules?|procedure|order amending|amend(?:ment|ing)|administrative (?:order|directive)|standing order|rule \d)')
def ext(r):
  p=r['local_path'];b=open(p,'rb').read();ld=None
  if b[:5]==b'%PDF-':
    t=subprocess.run(['pdftotext','-layout',p,'-'],capture_output=True,timeout=120).stdout.decode('utf-8','replace');k='pdf'
  elif b[:2]==b'PK':
    try:
      import docx; t='\n'.join(x.text for x in docx.Document(p).paragraphs);k='docx'
    except Exception: t='';k='zip_unparsed'
  elif b.lstrip()[:1]==b'<' or 'html' in r['mime']:
    s=BeautifulSoup(b,'html.parser')
    for x in s(['script','style','noscript','nav','header','footer','form']):x.decompose()
    t=s.get_text('\n');k='html'
    aw=sum(len(a.get_text().split()) for a in s.find_all('a'));tw=len(t.split()) or 1;ld=aw/tw
  else:
    t='';k='binary_unparsed'  # .doc/.ppt OLE: no extractor on box
  t=re.sub(r'[ \t]+',' ',re.sub(r'\n\s*\n+','\n\n',t)).strip()
  return k,t,ld
def decide(r,k,t,ld):
  w=len(t.split());cues=len(CUE.findall(t));subs=len(SUB.findall(t))
  tc=bool(TITLE.search(t[:600]+' '+r['original_url']))
  m=dict(kind=k,words=w,link_density=None if ld is None else round(ld,3),rule_cues=cues,subsection_marks=subs,title_cue=tc)
  if not t: return False,'no_text_extracted',m
  if w<150: return False,'too_short(<150 words)',m
  if ld is not None and ld>0.4: return False,'navigation(link_density>0.4)',m
  blanks=len(re.findall(r'_{5,}',t));m['form_blanks']=blanks
  if blanks>=8 and not re.search(r'(?i)\brules? of\b|order amending|administrative order',t[:800]): return False,'form_not_rule(>=8 fill-in blanks, no rule/order title)',m
  h=t[:700]
  if (re.match(r'(?i)\s*form\s+\d',t) or (re.search(r'(?i)plaintiff',h) and re.search(r'(?i)defendant',h) and re.search(r'(?i)C\.\s*A\.\s*No|Case No|Civil Action No',h))) and not re.search(r'(?i)standing order|administrative order|order amending|rules? of',h): return False,'case_caption_template(form/pleading template, not a rule)',m
  if re.match(r'(?i)\s*memorandum\b',t): return False,'memorandum_not_rule',m
  if cues+subs>=5: return True,'rule_structure(cues+subsections>=5)',m
  if tc and w>=300 and (ld is None or ld<=0.25): return True,'title_cue+>=300 words+low link density',m
  return False,'no_rule_structure',m
out=[];log=open(f'{RV}/filter_log.jsonl','w');cnt=collections.Counter()
for f in sorted(glob.glob(f'{A}/[A-Z][A-Z].jsonl')):
  for l in open(f):
    r=json.loads(l);k,t,ld=ext(r);keep,why,m=decide(r,k,t,ld);st=r['subdivision_iso'][3:]
    cnt[(st,keep)]+=1
    log.write(json.dumps(dict(rule_id=r['rule_id'],state=st,original_url=r['original_url'],content_sha256=r['content_sha256'],keep=keep,reason=why,**m,text_sha256=hashlib.sha256(t.encode()).hexdigest()))+'\n')
    if keep: r['text']=t;r['text_extraction']=k;r['text_sha256']=hashlib.sha256(t.encode()).hexdigest();out.append(r)
with open(f'{RV}/filter_survivors.jsonl','w') as o:
  for r in out:o.write(json.dumps(r)+'\n')
print({f'{s}':(cnt[(s,True)],cnt[(s,False)]) for s in sorted({s for s,_ in cnt})})
