#!/usr/bin/env python3
"""Adapt Austria memsafe pack tip 67e8dd6529d0 → tip 096bd65e89d3.

UPDATE_EXPAND after Hub deepen republish; floor ≥21959/224752.
German ASCII GATE re-attested from articles.parquet @ 096bd65e89d3.
URL ogd.ris.bka.gv.at / www/http/https/gv/at query-only, NEVER GATE.
HOLD 0 STRICT; soft never-thin ON; SKIP_US; KW HOLD_THIN; IT leave alone.
Supersedes tip 67e8dd6529d0 (prior IR 29d2099fb076, corpus 201971).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re

ROOT = Path("/workspace/do_ir_resume")
SRC_TIP_FULL = "67e8dd6529d02e3d77f897e59c448a1001fa39db"
SRC_TIP_SHORT = "67e8dd6529d0"
DST_TIP_FULL = "096bd65e89d3247debcfee4d51541b37d14b4def"
DST_TIP_SHORT = "096bd65e89d3"
FLOOR_LAWS, FLOOR_ARTS = 21959, 224752
SRC_FLOOR_ARTS = 201971

# Re-attested @ tip 096bd65e89d3 articles.parquet (title+text sample)
GATE_YEARS = [
    "2018", "1994", "2025", "2004", "2002", "2019",
    "1999", "2006", "1997", "2020", "2003", "2021",
]
GATE_STEMS = [
    "osterreich", "ris", "bundesgesetz", "artikel", "absatz", "gesetz",
    "verordnung", "bgbl", "abs", "art", "anwendung", "bund",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT"
MODE = "UPDATE_EXPAND"

FILES = [
    ("austria_soft_filter.py", "austria_soft_filter.py"),
    (f"austria_corpus_stream_{SRC_TIP_SHORT}.py", f"austria_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"austria_encode_memsafe_{SRC_TIP_SHORT}.py", f"austria_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"austria_finish_from_emb_{SRC_TIP_SHORT}.py", f"austria_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"austria_stream_graph_parts_{SRC_TIP_SHORT}.py", f"austria_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"austria_package_stream_{SRC_TIP_SHORT}.py", f"austria_package_stream_{DST_TIP_SHORT}.py"),
    ("austria_upload.py", "austria_upload.py"),
    ("austria_bm25_smoke.py", "austria_bm25_smoke.py"),
    ("austria_write_publish_report.py", "austria_write_publish_report.py"),
    ("austria_tip_check.py", "austria_tip_check.py"),
    (f"austria_orchestrator_{SRC_TIP_SHORT}.py", f"austria_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    for bad in ("cient-data", "prent-data", "stent-data", "austriaent-data"):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")

    # Protect mode / hold placeholders
    text = text.replace("UPDATE_EXPAND", "\x00DESTMODE\x00")
    text = text.replace("RECONFIRM_FINAL", "\x00DESTMODE\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")

    # Tip swaps then protect
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    # Floor arts 201971 → 224752 (laws stay 21959)
    text = text.replace("21959/201971", "\x00FLOOR_LA\x00")
    text = text.replace("21959 / 201971", "\x00FLOOR_LA_SP\x00")
    text = text.replace("21959, 201971", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 21959, 201971", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 21959, 201971", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('or 201971)', "\x00OR_ARTS_PAREN\x00")
    text = text.replace('"articles": 201971', '"articles": \x00ARTS\x00')
    text = text.replace("'articles': 201971", "'articles': \x00ARTS\x00")
    text = text.replace(" 201971", "\x00ARTS\x00")
    text = text.replace("201971", "\x00ARTS\x00")

    text = text.replace("\x00FLOOR_LA\x00", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    text = text.replace("\x00FLOOR_LA_SP\x00", f"{FLOOR_LAWS} / {FLOOR_ARTS}")
    text = text.replace("\x00FLOOR_LA_C\x00", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    text = text.replace("\x00FLOOR_ASSIGN\x00", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", f"FLOOR_L, FLOOR_A = {FLOOR_LAWS}, {FLOOR_ARTS}")
    text = text.replace("\x00OR_ARTS_PAREN\x00", f"or {FLOOR_ARTS})")
    text = text.replace("\x00ARTS\x00", str(FLOOR_ARTS))

    text = text.replace("\x00DESTMODE\x00", MODE)
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)

    if dst_name == "austria_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        note = (
            f"attested years {GATE_NOTE_YEARS} plus German ASCII stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL ogd.ris.bka.gv.at / "
            f"www/http/https/gv/at are query-only, not GATE."
        )
        text = re.sub(
            r'"tokenizer_note":\s*\'[^\']*\'',
            f'"tokenizer_note": \'{note}\'',
            text,
            count=1,
        )
        text = re.sub(
            r'"tokenizer_note":\s*"[^"]*"',
            f'"tokenizer_note": "{note}"',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Austria IR — German legal corpus; years + German ASCII stems FTS gate.\n\n'
            "GATE is attested ASCII years plus German legal stems that rank at tip "
            f"{DST_TIP_SHORT}.\n"
            "URL tokens (www/http/https/gv/at, ogd.ris.bka.gv.at) are query-only, NEVER GATE.\n"
            "Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )

    if dst_name == "austria_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on German/Austrian ASCII GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}; "
            f"URL query-only)"
        )
        text = re.sub(
            r'"BM25 PASS on [^"]*"',
            f'"{gate_note}"',
            text,
            count=1,
        )
        # supersedes note
        if "supersedes" not in text.lower():
            text = text.replace(
                f'"mode": "{MODE}"',
                f'"mode": "{MODE}",\n    "supersedes_tip": "{SRC_TIP_SHORT}",\n    "prior_ir": "29d2099fb076"',
            )

    if dst_name == "austria_soft_filter.py":
        text = text.replace(
            "tip pack through with floor checks only (UPDATE_EXPAND).",
            "tip pack through with floor checks only (UPDATE_EXPAND after deepen).",
        )
        text = re.sub(
            r'"""Soft filter for Austria tip .*?"""',
            f'"""Soft filter for Austria tip {DST_TIP_SHORT} — memsafe pass-through.\n\n'
            f"Full chrome iterrows OOM risk at {FLOOR_ARTS} arts. Floor matches hub;\n"
            f"soft never-thin ON. Copy tip pack through with floor checks only "
            f"({MODE} after deepen).\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )

    if dst_name.endswith(f"orchestrator_{DST_TIP_SHORT}.py"):
        # rewrite PHASES script names that still reference src tip filenames
        text = text.replace(
            f"austria_corpus_stream_{SRC_TIP_SHORT}.py",
            f"austria_corpus_stream_{DST_TIP_SHORT}.py",
        )
        text = text.replace(
            f"austria_encode_memsafe_{SRC_TIP_SHORT}.py",
            f"austria_encode_memsafe_{DST_TIP_SHORT}.py",
        )
        text = text.replace(
            f"austria_finish_from_emb_{SRC_TIP_SHORT}.py",
            f"austria_finish_from_emb_{DST_TIP_SHORT}.py",
        )
        text = text.replace(
            f"austria_stream_graph_parts_{SRC_TIP_SHORT}.py",
            f"austria_stream_graph_parts_{DST_TIP_SHORT}.py",
        )
        text = text.replace(
            f"austria_package_stream_{SRC_TIP_SHORT}.py",
            f"austria_package_stream_{DST_TIP_SHORT}.py",
        )
        text = re.sub(
            r'"""Austria.*?"""',
            f'"""Austria {MODE} orchestrator tip {DST_TIP_SHORT} '
            f"(memsafe corpus+encode; {HOLD}; German GATE; supersedes {SRC_TIP_SHORT}).\"\"\"",
            text,
            count=1,
            flags=re.S,
        )

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if str(SRC_FLOOR_ARTS) in text:
        raise RuntimeError(f"old arts floor leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name
        for x in ("soft_filter", "orchestrator", "bm25_smoke", "upload", "tip_check", "write_publish")
    ):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    if "\x00" in text:
        raise RuntimeError(f"null placeholder leftover in {dst_name}")

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = [") : text.index("]", text.index("GATE = [")) + 1]
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing stem in GATE: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE: {year}")
        for bad in ("shall", "loi", "ghana", "portugal", "lei"):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-AT token in GATE: {bad}")
    return text


def main() -> None:
    for src_name, dst_name in FILES:
        src = ROOT / src_name
        if not src.is_file():
            raise FileNotFoundError(src)
        raw = src.read_text(encoding="utf-8")
        (ROOT / dst_name).write_text(adapt(raw, dst_name), encoding="utf-8")
        print(f"wrote {dst_name}")
    print("GATE years", GATE_YEARS)
    print("GATE stems", GATE_STEMS)
    print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
    print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; {MODE}; {HOLD}")


if __name__ == "__main__":
    main()
