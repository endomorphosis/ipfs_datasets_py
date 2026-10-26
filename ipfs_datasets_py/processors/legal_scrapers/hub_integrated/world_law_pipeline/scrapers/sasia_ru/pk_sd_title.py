import re
JUNK=re.compile(r'^(scan to verify|law department|legal department|government of sindh|registered no.*|karachi.*|notification|page \d+.*)$',re.I)
KEY=re.compile(r'\b(ACT|ORDINANCE|RULES|REGULATIONS?|ORDER|BILL|NOTIFICATION|CODE)\b')
def title(text):
    out=[]
    for raw in text.splitlines()[:60]:
        for seg in re.split(r'\s{3,}',raw.strip()):
            s=re.sub(r'\s+',' ',seg).strip(' .')
            if len(s)>3 and not JUNK.match(s): out.append(s)
    for i,s in enumerate(out):
        if KEY.search(s) and s.upper()==s:
            t=s
            if re.match(r'^(SINDH|SIND) (ACT|ORDINANCE) NO',t) and i+1<len(out): t+='. '+out[i+1]
            elif i+1<len(out) and out[i+1].upper()==out[i+1] and not t.endswith(('ACT, 20','ACT')) and len(t)<60: t+=' '+out[i+1]
            return t[:300]
    return ' '.join(out[:2])[:300] or None
