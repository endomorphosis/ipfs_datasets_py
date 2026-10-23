import sys
sys.path.insert(0, ".")
import za_pdf_tranche_build as B
works = B.load_excluded()
w = [x for x in works if x["work"].endswith("by-law/1996/water-supply")][0]
print("pre-OCR water", w["work"], flush=True)
streams, method = B.get_streams(w)
print("done water", method, "linear chars",
      sum(len(p) for p in streams.get("linear", [])), flush=True)
print("PRE-OCR WATER DONE", flush=True)
