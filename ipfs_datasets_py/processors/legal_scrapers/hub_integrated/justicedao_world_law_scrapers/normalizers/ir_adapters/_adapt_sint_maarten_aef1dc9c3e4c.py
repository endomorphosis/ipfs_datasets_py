#!/usr/bin/env python3
"""Adapt the Montserrat FIRST_IR memsafe pack to Sint Maarten SX."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import json

ROOT = Path("/workspace/do_ir_resume")
SRC_TIP_FULL = "0934a8280dead70835c8f3cda66a9b36771555cb"
SRC_TIP_SHORT = "0934a8280dea"
DST_TIP_FULL = "aef1dc9c3e4c7521e9f17200db58f012da2615d0"
DST_TIP_SHORT = "aef1dc9c3e4c"
FLOOR_LAWS, FLOOR_ARTS = 175, 9073
GATE_YEARS = [2010, 2012, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021]
GATE_STEMS = ["artikel", "landsverordening", "integriteitskamer", "bestuursorgaan", "regering", "sint", "maarten", "worden", "eerste"]

FILES = [
    ("montserrat_soft_filter.py", "sint_maarten_soft_filter.py"),
    (f"montserrat_corpus_stream_{SRC_TIP_SHORT}.py", f"sint_maarten_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"montserrat_encode_memsafe_{SRC_TIP_SHORT}.py", f"sint_maarten_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"montserrat_finish_from_emb_{SRC_TIP_SHORT}.py", f"sint_maarten_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"montserrat_stream_graph_parts_{SRC_TIP_SHORT}.py", f"sint_maarten_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"montserrat_package_memsafe_{SRC_TIP_SHORT}.py", f"sint_maarten_package_memsafe_{DST_TIP_SHORT}.py"),
    ("montserrat_upload.py", "sint_maarten_upload.py"),
    ("montserrat_bm25_smoke.py", "sint_maarten_bm25_smoke.py"),
    ("montserrat_write_publish_report.py", "sint_maarten_write_publish_report.py"),
    (f"montserrat_orchestrator_{SRC_TIP_SHORT}.py", f"sint_maarten_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_montserrat_laws", "endomorphosis/ipfs_sint_maarten_laws"),
        ("justicedao/ipfs_montserrat_laws_ir", "justicedao/ipfs_sint_maarten_laws_ir"),
        ("ipfs_montserrat_laws_ir", "ipfs_sint_maarten_laws_ir"),
        ("ipfs_montserrat_laws", "ipfs_sint_maarten_laws"),
        ("HOLD 0 STRICT after-TG (HT→VG→SX→CD→BM)", "HOLD 0 STRICT after-VG (CD→BM)"),
        ("after-TG (HT→VG→SX→CD→BM)", "after-VG (CD→BM)"),
        ("after-TG", "after-VG"),
        ("HT→VG→SX→CD→BM", "CD→BM"),
        ("www/gov/ms", "www/gov/sx"),
        ("English (Montserrat)", "Dutch (Sint Maarten)"),
        ("English Montserrat", "Dutch Sint Maarten"),
        ("Montserrat", "Sint Maarten"),
        ("montserrat", "sint_maarten"),
        ('"MS"', '"SX"'),
        ("MS-attested", "SX-attested"),
        ("(MS)", "(SX)"),
        ("/ms", "/sx"),
        ("English", "Dutch"),
        ("9650", "9073"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    if dst_name == "sint_maarten_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        gate = ("GATE_YEARS = [\n"
                "    \"2010\", \"2012\", \"2014\", \"2015\", \"2016\", \"2017\", \"2018\", \"2019\", \"2020\", \"2021\",\n"
                "]\n"
                "GATE_STEMS = [\n"
                "    \"artikel\", \"landsverordening\", \"integriteitskamer\", \"bestuursorgaan\", \"regering\", \"sint\", \"maarten\", \"worden\", \"eerste\",\n"
                "]\n"
                "GATE = GATE_YEARS + GATE_STEMS")
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "ms", "article", "legal", "regulation", "minister", "court"]',
            'QUERIES = GATE + ["www", "gov", "sx", "article", "legal", "regulation", "minister", "court", "law", "shall"]')
        text = text.replace(
            '    ok = all(q in detail["ranked"] for q in GATE)',
            '    missing_stems = [q for q in GATE_STEMS if q not in detail["ranked"]]\n'
            '    selected_gate = GATE if not missing_stems else GATE_YEARS\n'
            '    gate_fallback = bool(missing_stems)\n'
            '    ok = all(q in detail["ranked"] for q in selected_gate)')
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith('    detail.update({'):
                lines[i] = ('    detail.update({"pass": ok, "tokenizer_note": "ASCII-after-diacritic-fold tokenizer ([0-9A-Za-z]+); '
                            'preferred GATE = attested years 2010/2012/2014/2015/2016/2017/2018/2019/2020/2021 plus Dutch legal stems '
                            'artikel/landsverordening/integriteitskamer/bestuursorgaan/regering/sint/maarten/worden/eerste from articles.parquet '
                            'HEAD tip aef1dc9c3e4c; English law/shall are query-only; URL www/gov/sx is query-only, not GATE.", '
                            '"sint_maarten_pass": ok, "sint_maarten_gate": selected_gate, "gate_preferred": GATE, '
                            '"gate_fallback_years_primary": gate_fallback, "missing_dutch_stems": missing_stems, '
                            '"hub_commit_expected": None, "tip": "aef1dc9c3e4c"})')
        text = "\n".join(lines) + "\n"
        text = text.replace(
            '"n_gate_ranked": sum(q in detail["ranked"] for q in GATE), "n_gate": len(GATE), "gate": GATE',
            '"n_gate_ranked": sum(q in detail["ranked"] for q in selected_gate), "n_gate": len(selected_gate), "gate": selected_gate, "gate_preferred": GATE, "gate_fallback_years_primary": gate_fallback, "missing_dutch_stems": missing_stems')

    if dst_name == "sint_maarten_write_publish_report.py":
        text = text.replace(
            "1967/2000/2002/2005/2008/2011/2013/2019/2020/2025 + stems shall/assembly/governor/person/sint_maarten/constitution/act/section/legislative/committee/member/office",
            "2010/2012/2014/2015/2016/2017/2018/2019/2020/2021 + Dutch stems artikel/landsverordening/integriteitskamer/bestuursorgaan/regering/sint/maarten/worden/eerste")
        text = text.replace(
            "Dutch GATE (attested years 2010/2012/2014/2015/2016/2017/2018/2019/2020/2021 + stems artikel/landsverordening/integriteitskamer/bestuursorgaan/regering/sint/maarten/worden/eerste); URL www/gov/sx is query-only, not GATE",
            "Dutch GATE (attested years 2010/2012/2014/2015/2016/2017/2018/2019/2020/2021 + stems artikel/landsverordening/integriteitskamer/bestuursorgaan/regering/sint/maarten/worden/eerste; English law/shall and URL www/gov/sx are query-only, not GATE)")

    if "Montserrat" in text or "montserrat" in text or "Nauru" in text or "French" in text or "Gabon" in text or "Togo" in text:
        raise RuntimeError(f"country/language/queue leftovers in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_ps.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "sint_maarten":
        entry.update({
            "tip": DST_TIP_SHORT,
            "tip_full": DST_TIP_FULL,
            "laws": FLOOR_LAWS,
            "articles": FLOOR_ARTS,
            "floor_laws": FLOOR_LAWS,
            "floor_articles": FLOOR_ARTS,
            "claim_tip": DST_TIP_SHORT,
            "match_claim": True,
            "ir_hub_head": None,
            "true_first_ir": True,
            "thin": False,
            "label": "EXPAND",
            "soft_never_thin": True,
            "skip_us": True,
            "italy_blocked": True,
            "language": "Dutch (Sint Maarten)",
            "years_attested": [2018, 2014, 2019, 2020, 2021, 2017, 2022, 2025, 2015, 2010, 2016, 2012],
            "gate_years": GATE_YEARS,
            "gate_stems": GATE_STEMS,
            "note": "SX FIRST_IR scaffold; tip MATCH aef1dc9c3e4c@175/9073; HOLD 0 STRICT; queue after-VG (CD→BM)",
        })
        break
else:
    raise RuntimeError("Sint Maarten entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Sint Maarten entry")
