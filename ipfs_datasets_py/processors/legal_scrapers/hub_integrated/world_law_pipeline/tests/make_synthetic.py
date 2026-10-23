"""Build a synthetic staging tree for run_loop tests (never upload this)."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schema as S

def w(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")
    os.rename(tmp, path)
    os.utime(path, (1, 1_700_000_000))  # old mtime -> passes --min-age

def main(root):
    st = Path(root)
    base = dict(S.EXAMPLE_RECORD)
    nl = [dict(base, doc_id=f"CVDR{i}", doc_order=i, title_native=f"Verordening {i}") for i in range(3)]
    w(st / "scraper_b/NL/wd_Q727.b1.jsonl", nl)
    bad = [dict(base, doc_id="CVDR9"),
           dict(base, doc_id="CVDRx", doc_type="bylaw"),                     # bad enum
           dict(base, doc_id="CVDRy", published_date="01/02/2024"),         # bad date
           dict(base, doc_id="CVDRz", place_id="wd:Q9999"),                  # wrong file
           dict(base, doc_id="CVDRw", html=None, text=None),                 # no content
           "{not json"]
    w(st / "scraper_b/NL/wd_Q727.b2.jsonl", bad)
    fr = [{"place_id": "iso:FR", "country_code": "FR", "doc_id": "LEGITEXT000006070633",
           "source_platform": "legifrance", "source_url": "https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000006070633",
           "doc_type": "statute", "language": "fr", "title_native": "Code général des collectivités territoriales",
           "in_force": "true", "consolidated": True, "content_format": "xml", "text": "Article L1111-1 ...",
           "retrieved_at": "2026-10-10T21:00:00", "place_name": "France", "qid": "Q142"}]
    w(st / "national/FR/iso_FR.20261010.jsonl", fr)
    us = [{"place_id": "gnis:1008538", "country_code": "US", "gnis": "1008538", "doc_id": "PTIICOOR_CH1",
           "source_platform": "municode", "source_url": "https://library.municode.com/x", "doc_type": "code_section",
           "language": "en", "html_title": "<div class=\"chunk-title\">Chapter 1</div>",
           "html": "<div class=\"chunk-content\"><p>x</p></div>", "consolidated": True, "content_format": "html",
           "state_code": "CA", "place_name": "Example City"}]
    w(st / "scraper_a/US/1008538.jsonl", us)
    w(st / "scraper_b/NL/Bad Name!.jsonl", nl[:1])
    (st / "scraper_b/NL/wd_Q90.jsonl.tmp").write_text("partial")          # in progress -> ignored
    (st / "national/_logs").mkdir(parents=True, exist_ok=True); (st / "national/_logs/x.jsonl").write_text("{}\n")
    (st / "scraper_c/JP").mkdir(parents=True, exist_ok=True)
    (st / "scraper_c/JP/wd_Q1490.parquet").write_bytes(b"not a parquet")
    os.utime(st / "scraper_c/JP/wd_Q1490.parquet", (1, 1_700_000_000))
    print("synthetic staging at", st)

if __name__ == "__main__":
    main(sys.argv[1])
