#!/usr/bin/env python3
import json, re, sys
from pathlib import Path
sys.path.insert(0, '.')
from common import split_articles, ARTICLE_SPLIT

inst = Path('/workspace/legal-corpora/it/instruments')
# Broader IT-specific pattern: line-start Art. N optionally with title in parens
IT_ART = re.compile(
    r'(?im)^\s*((?:Art\.|Articolo|ART\.)\s*\d+[a-zA-Z]?)\b'
)
# Also: Art. N (Title). - mid document after newlines from br
IT_ART2 = re.compile(
    r'(?m)(?<![\w.])((?:Art\.|Articolo)\s+\d+[a-zA-Z]?)(?:\s*\([^)]{0,120}\))?\s*(?:\.|-|–|:)'
)

stats = {
    'n':0,'has_docs':0,'docs_total':0,
    'split_articles_ge2':0,'split_new_ge2':0,
    'it_art_ge2':0,'it_art2_ge2':0,
    'would_gain_arts':0,'gain_arts':0,
    'short_abrog':0,'short_other':0,'ok_no_split':0,
}
abrog = re.compile(r'PROVVEDIMENTO ABROGATO|DECRETO DECADUTO', re.I)
examples=[]
for p in inst.glob('*.json'):
    d=json.loads(p.read_text(encoding='utf-8'))
    text=str(d.get('text') or '')
    docs=d.get('documents') or []
    stats['n']+=1
    if docs:
        stats['has_docs']+=1
        stats['docs_total']+=len(docs)
    tl=len(text.strip())
    if tl<80 and abrog.search(text):
        stats['short_abrog']+=1
        continue
    if tl<80:
        stats['short_other']+=1
    sa=split_articles(text, d.get('id') or p.stem, d.get('source_url') or '')
    it1=list(IT_ART.finditer(text))
    it2=list(IT_ART2.finditer(text))
    if len(sa)>=2: stats['split_articles_ge2']+=1
    if len(it1)>=2: stats['it_art_ge2']+=1
    if len(it2)>=2: stats['it_art2_ge2']+=1
    # prefer IT_ART line splits rebuilt
    matches=it1 if len(it1)>=2 else []
    new_docs=[]
    if len(matches)>=2:
        for i,m in enumerate(matches):
            start=m.start(); end=matches[i+1].start() if i+1<len(matches) else len(text)
            chunk=text[start:end].strip()
            if len(chunk)<40: continue
            num=re.sub(r'\s+',' ', m.group(1)).strip()
            new_docs.append(num)
    if len(new_docs)>=2 and len(new_docs)>len(docs):
        stats['would_gain_arts']+=1
        stats['gain_arts']+=len(new_docs)-len(docs)
        if len(examples)<5:
            examples.append((p.name, len(docs), len(new_docs), new_docs[:6], tl))
    elif len(sa)>=2 and len(sa)>len(docs):
        stats['split_new_ge2']+=1
        stats['would_gain_arts']+=1
        stats['gain_arts']+=len(sa)-len(docs)
    elif tl>=200 and len(docs)<2:
        stats['ok_no_split']+=1

print(json.dumps(stats, indent=2))
print('examples', examples)
