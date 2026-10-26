#!/usr/bin/env python3
"""Repair 'fi'/'fl' ligatures that pdftotext dropped (e.g. 'identi kačné' for 'identifikačné'): re-read the same cached PDF with
pdfminer.six (which emits U+FB01/U+FB02, NFKC -> 'fi'/'fl'), collect the ligature words, and restore them in the pdftotext text
where the word appears with the ligature missing ('identi kačné' / 'identikačné'). No OCR.
Usage: sk_ligature_fix.py RAW.jsonl NATIVE_ID PDF_PATH  (rewrites RAW.jsonl in place; keeps RAW.jsonl.bak)"""
import json, re, sys, shutil, unicodedata, collections
from pdfminer.high_level import extract_text

def repair(text, pdf):
    ref = unicodedata.normalize("NFKC", extract_text(pdf))
    words = {w for w in re.findall(r"\w*f[il]\w*", ref) if re.search(r"\w(f[il])|(f[il])\w", w)}
    n = 0
    for w in sorted(words, key=len, reverse=True):
        for m in re.finditer(r"f[il]", w):
            a, b = w[:m.start()], w[m.end():]
            if len(a) < 2 or len(b) < 2: continue
            rx = r"(?<!\w)" + re.escape(a) + r"[ \u00a0]?" + re.escape(b) + r"(?!\w)"
            text, k = re.subn(rx, w, text); n += k
    return text, n

if __name__ == "__main__":
    raw, nid, pdf = sys.argv[1:4]
    shutil.copy(raw, raw + ".bak")
    out = []
    for l in open(raw):
        d = json.loads(l)
        if d["native_id"] == nid:
            d["text"], n = repair(d["text"], pdf)
            d["extras"]["ligature_repairs"] = n; print(nid, "repairs", n)
        out.append(json.dumps(d, ensure_ascii=False))
    open(raw, "w").write("\n".join(out) + "\n")
