#!/usr/bin/env python3
"""Wave 11 Latin-script language correction.

The harvester's script check cannot separate Latin-script languages,
and several FAOLEX country sets mix local-language originals with
English translations (gui* e-files = UN DOALOS English; hai* e-files =
US State Dept English). Wave-10 precedent corrected Belarus by script;
here a stopword vote corrects the label. Only instruments NOT already
on HF (not in wave11/dedupe) are touched, and only on a decisive vote.

Usage: fix_lang.py <cc> <lang_a> <lang_b>
Votes between lang_a/lang_b stopword sets (en/fr/bs supported).
Prints and logs flips to wave11/stats/fix_lang_{cc}.json.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common11 import WAVE11

INST_BASE = os.path.expanduser('~/.ipfs_datasets/legal-corpora')
STOP = {
    'en': ['the', 'of', 'and', 'in', 'to', 'shall', 'article', 'law', 'section',
           'this', 'for', 'by', 'with', 'on', 'act', 'government', 'republic'],
    'fr': ['le', 'la', 'les', 'de', 'des', 'du', 'et', 'est', 'dans', 'qui',
           'au', 'aux', 'article', 'loi', 'pour', 'par', 'ministre', 'république',
           'décret', 'président'],
    'bs': ['je', 'se', 'na', 'od', 'za', 'člana', 'član', 'zakona', 'ovim',
           'donosi', 'federacije', 'službene', 'novine', 'uređuje', 'ovog',
           'izmjene', 'dopune', 'bosne', 'hercegovine'],
}

def score(text, lang):
    words = STOP[lang]
    t = ' ' + re.sub(r'\s+', ' ', text.lower()) + ' '
    return sum(t.count(' ' + w + ' ') for w in words)

def main():
    cc, la, lb = sys.argv[1], sys.argv[2], sys.argv[3]
    dedupe = json.load(open(os.path.join(WAVE11, 'dedupe', f'{cc}_dedupe.json')))
    hf_ids = {r['id'] for r in dedupe}
    inst_dir = os.path.join(INST_BASE, cc, 'instruments')
    flips, checked = [], 0
    for fn in sorted(os.listdir(inst_dir)):
        if not fn.endswith('.json'):
            continue
        iid = fn[:-5]
        if iid in hf_ids:
            continue
        p = os.path.join(inst_dir, fn)
        rec = json.load(open(p))
        if rec.get('language') not in (la, lb):
            continue
        text = (rec.get('text') or '')[:4000]
        sa, sb = score(text, la), score(text, lb)
        checked += 1
        winner = None
        if sa >= 8 and sa >= 2 * max(sb, 1):
            winner = la
        elif sb >= 8 and sb >= 2 * max(sa, 1):
            winner = lb
        if winner and winner != rec['language']:
            flips.append({'id': iid, 'from': rec['language'], 'to': winner,
                          'scores': {la: sa, lb: sb}})
            rec['language'] = winner
            json.dump(rec, open(p, 'w'), ensure_ascii=False)
    out = {'cc': cc, 'pair': [la, lb], 'checked_new': checked, 'flips': flips}
    json.dump(out, open(os.path.join(WAVE11, 'stats', f'fix_lang_{cc}.json'), 'w'), indent=1)
    print(json.dumps(out))

if __name__ == '__main__':
    main()
