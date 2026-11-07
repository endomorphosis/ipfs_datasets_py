#!/usr/bin/env python3
"""Atomically mirror czp_* + collectors keys (and only those) from soft_lean PIN to main PIN (collector writes only soft_lean)."""
import json,os,sys
EXTRA=sys.argv[sys.argv.index('--prefix')+1] if '--prefix' in sys.argv else None  # opt-in e.g. eep_ (EE second collector); default keys unchanged
A='/workspace/logs/soft_lean/HOLD_AT_PIN.state'; B='/workspace/logs/HOLD_AT_PIN.state'
a=json.load(open(A)); b=json.load(open(B)); ch=0
for k,v in a.items():
    if (k.startswith('czp_') or k=='collectors' or (EXTRA and k.startswith(EXTRA))) and b.get(k)!=v: b[k]=v; ch+=1
if ch: json.dump(b,open(B+'.mirror.tmp','w'),indent=1); os.replace(B+'.mirror.tmp',B)
print('mirrored',ch,'keys; collectors=',b.get('collectors'))
