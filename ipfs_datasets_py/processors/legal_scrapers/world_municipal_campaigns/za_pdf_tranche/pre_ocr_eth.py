import sys
sys.path.insert(0, ".")
import za_pdf_tranche_build as B

works = B.load_excluded()
targets = ["mn/1998/50", "mn/1999/7", "mn/2012/20"]
for t in targets:
    w = [x for x in works if x["work"].endswith(t)][0]
    print("pre-OCR", w["work"], flush=True)
    streams, method = B.get_streams(w)
    total = sum(len(p) for p in streams.get("linear", []))
    print("done", w["work"], method, "linear chars", total, flush=True)
print("PRE-OCR DONE")
