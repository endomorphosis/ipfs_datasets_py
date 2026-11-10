import re,sys,html,urllib.parse
from rules_common import *
def idx(u,pat=r"\.pdf|download|rules"):
    b,eu,pol=polite_get(u);print("==",u,pol,len(b) if b else None)
    if not b: return
    t=b.decode("utf-8","replace")
    seen=set()
    for h,x in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',t,re.S):
        x=re.sub(r"<[^>]+>|\s+"," ",html.unescape(x)).strip()
        h=html.unescape(h)
        if re.search(pat,h,re.I) and (h,x) not in seen and x:
            seen.add((h,x));print(urllib.parse.urljoin(u,h),"|",x[:90])
if __name__=="__main__": idx(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else r"\.pdf|download|rules")
