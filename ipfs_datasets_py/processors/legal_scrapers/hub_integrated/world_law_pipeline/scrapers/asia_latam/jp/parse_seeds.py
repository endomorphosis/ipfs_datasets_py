import re, json, html, collections
from urllib.parse import urlparse
t=open('ml_reikishu.txt').read()
rows=re.findall(r'<tr(?: class="([^"]*)")? data-pref="([^"]+)" data-name="([^"]+)"><th[^>]*>.*?</th><td class="opm-ml-url">(.*?)</td></tr>',t,re.S)
out=[]
for cls,pref,name,td in rows:
    urls=[html.unescape(u) for u in re.findall(r'href="([^"]+)"',td)]
    out.append(dict(pref=pref,name=name,is_pref='pref' in cls,urls=urls))
json.dump(out,open('seeds_raw.json','w'),ensure_ascii=False,indent=0)
print(len(out))
def cls_(u):
    p=urlparse(u); h=p.netloc; path=p.path
    if 'd1-law.com' in h: return 'd1law_ops'
    if 'd1w_reiki' in path: return 'd1w_reiki'
    if 'h-chosonkai' in h: return 'h_chosonkai'
    if 'legal-square' in h: return 'legal_square'
    if 'joureikun' in h or 'joureikun' in path: return 'joureikun'
    if 'g-reiki.net' in h: return 'g_reiki'
    if 'reiki_menu' in path or 'reiki_int' in path: return 'gyosei_reikibase'
    if h.startswith('reiki.'): return 'reiki_host'
    if '/reiki' in path: return 'own_reiki'
    return 'other:'+h
c=collections.Counter(); ex=collections.defaultdict(list)
for r in out:
    for u in r['urls'][:1]:
        k=cls_(u); c[k.split(':')[0]]+=1; ex[k.split(':')[0]].append(u)
print(c)
for k,v in ex.items(): print(k, v[:6])
