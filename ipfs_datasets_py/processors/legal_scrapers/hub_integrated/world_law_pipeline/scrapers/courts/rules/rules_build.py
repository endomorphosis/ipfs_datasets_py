"""Generic rule extraction + record building for HTML/text sources (and PDFs via rules_common.pdf_text)."""
import re,json,hashlib,datetime,os
from rules_common import *
HEAD=re.compile(r"^(?:RULE|Rule)\s+(?P<num>\d+(?:\.\d+)?[A-Za-z]?)\.[ ]*(?P<rest>.*)$",re.M)
PART=re.compile(r"^(?P<n>[IVXL]+)\.\s+(?P<t>[A-Z][A-Z0-9 ,;:&'’\-—–/()\[\]]{6,})$",re.M)
EFF=re.compile(r"(?:effective|Effective)\s+(?:date\s+)?(?:on\s+)?([A-Z][a-z]+\.?\s+\d{1,2},\s+\d{4})")
TAIL=re.compile(r"^(?:APPENDIX|Appendix|FORM\s+\d|FORMS?$|IN THE SUPREME COURT|ADKT\s+\d|ORDER (?:AMENDING|ADOPTING|REPEALING)|ORDER\b.{0,40}\bRULES)",re.M)
def first_num(n):
    return tuple(int(x) for x in re.findall(r"\d+",n))
CAPS=re.compile(r"^[A-Z][A-Z0-9 ,;:&'’\-—–/().]{9,200}$",re.M)
def _ok_head(m):
    r=m.group("rest").strip()
    return not ((r and (r[0].islower() or r[0].isdigit() or r[0] in "(“\"'")) or re.search(r"\.{4,}|(?:\. ){4,}",r))
def _prev_ok(text,m):
    prev=text[:m.start()].rstrip('\n').rsplit('\n',1)[-1].strip()
    return bool(m.group("rest").strip()) or not (prev and re.search(r"[a-z,]$",prev) and len(prev)>25)
SMALL=set("a an the of to in for and or by on at with as from nor under upon into than that which between per vs v".split())
def _titlecase(l):
    ws=[w for w in re.findall(r"[A-Za-z’'\-]+",l)]
    if not ws or len(l)>60 or re.match(r"^[\(\d\[]",l) or l.endswith("."): return False
    big=[w for w in ws if w.lower() not in SMALL]
    return bool(big) and all(w[0].isupper() for w in big)
def extract(text,head=HEAD,capsfilter=False,dropshort=False,titlewrap=False,capswrap=False):
    ms=[m for m in head.finditer(text) if _ok_head(m) and _prev_ok(text,m) and not re.search(r"\.{5,}|(?:\. ){5,}",text[m.end():m.end()+200].split("\n",2)[0]+" "+(text[m.end():m.end()+200].split("\n")[1] if "\n" in text[m.end():m.end()+200] else ""))];rules=[];warn=0
    # documents whose real headings are ALL-CAPS titles: reject mixed-case 'Rule N. Text' cross-references
    def _capsish(m):
        r=m.group("rest").strip()[:15];L=[c for c in r if c.isalpha()];return bool(L) and all(c.isupper() for c in L)
    ne=[m for m in ms if m.group("rest").strip()]
    if capsfilter and len(ne)>=10 and sum(_capsish(m) for m in ne)>=0.7*len(ne): ms=[m for m in ms if not m.group("rest").strip() or _capsish(m)]
    # consecutive duplicate number = page/continuation header, not a new rule
    ms2=[]
    for m in ms:
        if ms2 and ms2[-1].group("num")==m.group("num") and not m.group("rest").strip() and not re.search(r"Version in effect prior",text[max(0,m.start()-120):m.start()]) : continue
        ms2.append(m)
    ms=ms2
    caps=[(c.start(),c.group(0).strip()) for c in CAPS.finditer(text) if not re.match(r"^(RULE|PART)\s+\d",c.group(0))]
    # part headings positions
    parts=[(m.start(),m.group("n"),m.group("t").strip()) for m in PART.finditer(text)]
    for i,m in enumerate(ms):
        end=ms[i+1].start() if i+1<len(ms) else len(text)
        seg=text[m.end():end]
        if i+1==len(ms):
            t=TAIL.search(seg)
            if t: seg=seg[:t.start()]
        rest=m.group("rest").strip();body=seg.strip()
        if titlewrap and not rest and body:
            _l=body.split("\n",1)
            if len(_l[0])<140 and not re.match(r"^[a-z(\[]",_l[0].strip()): rest=_l[0].strip();body=_l[1].strip() if len(_l)>1 else ""
        if titlewrap and rest and not rest.endswith((".",":",";")):
            CONN=r"(?:or|and|of|the|in|to|for|a|an|by|on|with|from|at|under|upon|as|nor|than|that|which|between|into|other|its|their)$"
            capsish=all(c.isupper() for c in rest if c.isalpha())
            plen=len(rest)
            for _ in range(3):
                ls=body.split("\n",1)
                if not ls[0] or len(rest)>200: break
                nxt=ls[0].strip()
                if capsish:
                    ok=all(c.isupper() for c in nxt if c.isalpha()) and len(nxt)<90 and not nxt.endswith(".") or (all(c.isupper() for c in nxt if c.isalpha()) and len(nxt)<90 and re.search(r"[A-Z]",nxt))
                    if capswrap: ok=bool(re.search(r"[A-Z]",nxt)) and all(c.isupper() for c in nxt if c.isalpha()) and len(nxt)<90 and plen>=28 and not re.match(r"^(?:RULE|SECTION|PART|ARTICLE|\(?[a-z0-9]{1,3}\)|IN THE )",nxt)
                    else: ok=ok and not re.match(r"^(?:RULE|SECTION|PART|ARTICLE|\(?[a-z0-9]{1,3}\))",nxt) and bool(re.search(r"[,;&\-]$|\b(OR|AND|OF|THE|IN|TO|FOR|A|AN|BY|ON|WITH|FROM|AT)$",rest))
                else:
                    ok=bool(re.search(r"(?:^|\s)"+CONN,rest,re.I) or rest.endswith((",","-","/","(")) or _titlecase(nxt) or bool(re.fullmatch(r"[A-Z][A-Za-z’'\-]+(?: [A-Za-z’'\-]+)?",nxt))) and len(nxt)<110
                if not ok: break
                rest=rest+" "+nxt;plen=len(nxt);body=ls[1].strip() if len(ls)>1 else ""
                if not capsish and nxt.endswith("."): break
        split=False
        mm=re.match(r"^(.{2,170}?)\.(?:\s+|$)(.*)$",rest,re.S)
        if rest and mm and not re.search(r"\b(?:No|Inc|Co|Mr|Mrs|Dr|vs|v|U\.S|etc)$",mm.group(1)) and len(rest)>len(mm.group(1))+1:
            title,first=mm.group(1),mm.group(2);split=True
            body=(first+("\n" if first and body else "")+body).strip()
        elif rest: title=rest.rstrip(".")
        elif titlewrap and re.match(r"^[a-z(\[]",body.strip()): title=""
        else:
            lines=body.split("\n");title=lines[0].strip().rstrip(".") if lines else "";body="\n".join(lines[1:]).strip()
        part=[(n,t) for pos,n,t in parts if pos<m.start()]
        if len(title)>110 and split or len(title)>300: body=(rest+"\n"+body).strip();title=""
        if re.fullmatch(r"\[(?:Reserved|Repealed|Rescinded|Abrogated|Omitted|Deleted|Replaced|Moved)[^\]]*\]",body.strip(),re.I): continue
        if not body.strip("[] ") and re.search(r"\[(?:Reserved|Repealed|Rescinded|Abrogated|Omitted|Deleted|Replaced|Moved)",title,re.I): continue
        if len(body.strip("[] "))<(40 if dropshort else 1) and re.match(r"^\[?(Reserved|Repealed|Rescinded|Abrogated|Omitted|Deleted)\b",title,re.I): continue
        cp=[t for pos,t in caps if pos<m.start() and (i==0 or pos>ms[i-1].start())]
        if not cp:
            st_=[t for pos,t in caps if pos<m.start() and re.match(r"^(?:[A-Z]\.\s|PART\b|ARTICLE\b|TITLE\b|CHAPTER\b|SECTION\b)",t)]
            cp=st_[-1:]
        if re.search(r"Version in effect prior to|[Pp]rior version|Superseded version",text[max(0,m.start()-120):m.start()]): continue
        rules.append({"num":m.group("num"),"title":title,"body":body,"part":part[-1] if part else None,"caps_heading":cp[-1] if cp else None,"start":m.start()})
    return strip_toc(rules)
def strip_toc(rules):
    """drop a leading table-of-contents run: headings 0..j-1 where nums restart at j and bodies are much shorter than the rest."""
    import statistics
    nums=[r["num"] for r in rules]
    if len(nums)<6: return rules
    for j in range(2,len(nums)-2):
        if nums[j]==nums[0]:
            first=rules[:j];rest=rules[j:]
            if len(set(nums[:j])&set(nums[j:]))>=0.8*len(set(nums[:j])):
                if statistics.median(len(r["body"]) for r in first)<0.4*statistics.median(len(r["body"]) for r in rest): return rest
            break
    return rules
def eff_date(body):
    ds=EFF.findall(body)
    if not ds: return None
    best=None
    for d in ds:
        for f in ("%B %d, %Y","%b %d, %Y","%b. %d, %Y"):
            try:
                x=datetime.datetime.strptime(d.replace("  "," "),f).date()
                best=x if best is None or x>best else best;break
            except ValueError: pass
    return best.isoformat() if best else None
def now(): return datetime.datetime.now(datetime.UTC).isoformat()
def qa(rules):
    nums=[r["num"] for r in rules];dup=len(nums)-len(set(nums))
    inc=sum(1 for a,b in zip(nums,nums[1:]) if first_num(b)<first_num(a))
    lens=sorted(len(r["body"]) for r in rules)
    return {"n":len(rules),"dup":dup,"nonmonotonic":inc,"empty":sum(1 for l in lens if l<20),"median_len":lens[len(lens)//2] if lens else 0}
