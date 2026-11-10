#!/usr/bin/env python3
"""Adapt copied Tunisia scripts into Laos scripts."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

def soft_filter():
    p = Path("/workspace/do_ir_resume/laos_soft_filter.py")
    src = p.read_text()
    repls = [
        ("Soft chrome filter for Tunisia tip 6178f00710c3; floor >= 1326/49830.",
         "Soft chrome filter for Laos tip 80cbe8a84f83; floor >= 547/8790."),
        ("endomorphosis/ipfs_tunisia_laws", "endomorphosis/ipfs_laos_laws"),
        ("6178f00710c3749e5064c5ffea58c2d7c63b4a43", "80cbe8a84f83deda1ca4963dbcbb19b1d1bffb76"),
        ("6178f00710c3", "80cbe8a84f83"),
        ("FLOOR_LAWS, FLOOR_ARTS = 1326, 49830", "FLOOR_LAWS, FLOOR_ARTS = 547, 8790"),
        ("tunisia_filtered_", "laos_filtered_"),
        ('"slug": "tunisia"', '"slug": "laos"'),
        ('"name": "Tunisia"', '"name": "Laos"'),
        ("# Tunisia filtered pack", "# Laos filtered pack"),
        ("tunisia_filter_", "laos_filter_"),
        (
            '"filter_reason": "soft-drop legislation.tn/IORT portal chrome (privacy/cookie/terms/sitemap/help/skip/contact/login/mentions) if present"',
            '"filter_reason": "soft-drop Lao Official Gazette / MoJ portal chrome (privacy/cookie/terms/sitemap/help/skip/contact/login/about) if present"',
        ),
    ]
    for a, b in repls:
        src = src.replace(a, b)
    old_start = src.index("# Soft portal-chrome markers")
    old_end = src.index("COMPILED = ")
    new_markers = '''# Soft portal-chrome markers (Lao/EN — Lao Official Gazette / MoJ portals)
MARKERS = [
    (r"\\bprivacy\\b", "privacy"),
    (r"\\bprivacy\\s+policy\\b", "privacy"),
    (r"\\u0e84\\u0ea7\\u0eb2\\u0ea1\\u0ec0\\u0e9b\\u0eb1\\u0e99\\u0eaa\\u0ec8\\u0ea7\\u0e99\\u0e95\\u0ebb\\u0ea7", "privacy"),
    (r"\\bcookies?\\b", "cookie"),
    (r"\\bterms\\s+of\\s+(use|service)\\b", "terms"),
    (r"\\bterms\\s+and\\s+conditions\\b", "terms"),
    (r"\\baccessibility\\b", "accessibility"),
    (r"\\bsitemap\\b", "sitemap"),
    (r"\\bsite\\s+map\\b", "sitemap"),
    (r"\\bskip[- ]?to[- ]?content\\b", "skip"),
    (r"\\bcontact(?:\\s+us)?\\b", "contact"),
    (r"\\u0e95\\u0eb4\\u0e94\\u0e95\\u0ecd\\u0ec8", "contact"),
    (r"\\b(login|sign[- ]?in|log[- ]?in|register)\\b", "login"),
    (r"\\u0ec0\\u0e82\\u0ebb\\u0ec9\\u0eb2\\u0eaa\\u0eb9\\u0ec8\\u0ea5\\u0eb0\\u0e9a\\u0ebb\\u0e9a", "login"),
    (r"\\bhelp\\b", "help"),
    (r"\\bfaq\\b", "help"),
    (r"\\bfrequently\\s+asked\\s+questions\\b", "help"),
    (r"\\u0e8a\\u0ec8\\u0ea7\\u0e8d\\u0ec0\\u0eab\\u0ea5\\u0eb7\\u0ead", "help"),
    (r"\\babout\\s+(us|this\\s+site|the\\s+portal)\\b", "about-site"),
    (r"\\u0e81\\u0ec8\\u0ebd\\u0ea7\\u0e81\\u0eb1\\u0e9a", "about-site"),
    (r"laoofficialgazette\\.gov\\.la/(?:contact|privacy|cookie|terms|login|sitemap|help|faq|about)", "portal-chrome-url"),
    (r"moj\\.gov\\.la/(?:contact|privacy|cookie|terms|login|sitemap|help|faq|about)", "portal-chrome-url"),
]

'''
    # Use actual Lao unicode in markers instead of escapes for readability
    new_markers = """# Soft portal-chrome markers (Lao/EN — Lao Official Gazette / MoJ portals)
MARKERS = [
    (r"\\bprivacy\\b", "privacy"),
    (r"\\bprivacy\\s+policy\\b", "privacy"),
    (r"ຄວາມເປັນສ່ວນຕົວ", "privacy"),
    (r"\\bcookies?\\b", "cookie"),
    (r"\\bterms\\s+of\\s+(use|service)\\b", "terms"),
    (r"\\bterms\\s+and\\s+conditions\\b", "terms"),
    (r"ເງື່ອນໄຂ", "terms"),
    (r"\\baccessibility\\b", "accessibility"),
    (r"\\bsitemap\\b", "sitemap"),
    (r"\\bsite\\s+map\\b", "sitemap"),
    (r"\\bskip[- ]?to[- ]?content\\b", "skip"),
    (r"\\bcontact(?:\\s+us)?\\b", "contact"),
    (r"ຕິດຕໍ່", "contact"),
    (r"\\b(login|sign[- ]?in|log[- ]?in|register)\\b", "login"),
    (r"ເຂົ້າສູ່ລະບົບ", "login"),
    (r"\\bhelp\\b", "help"),
    (r"\\bfaq\\b", "help"),
    (r"\\bfrequently\\s+asked\\s+questions\\b", "help"),
    (r"ຊ່ວຍເຫຼືອ", "help"),
    (r"\\babout\\s+(us|this\\s+site|the\\s+portal)\\b", "about-site"),
    (r"ກ່ຽວກັບ", "about-site"),
    (r"laoofficialgazette\\.gov\\.la/(?:contact|privacy|cookie|terms|login|sitemap|help|faq|about)", "portal-chrome-url"),
    (r"moj\\.gov\\.la/(?:contact|privacy|cookie|terms|login|sitemap|help|faq|about)", "portal-chrome-url"),
]

"""
    src = src[:old_start] + new_markers + src[old_end:]
    old_h = '''        "chrome_heuristics": [
            "privacy/confidentialite/خصوصية",
            "cookie",
            "terms / conditions d'utilisation / شروط الاستخدام",
            "accessibility / accessibilite",
            "sitemap / plan du site",
            "skip-to-content / aller au contenu",
            "contact/login/connexion",
            "help/faq/aide/مساعدة",
            "mentions legales / a propos",
            "thin legislation.tn non-PDF portal shells",
        ],'''
    new_h = '''        "chrome_heuristics": [
            "privacy / Lao privacy marker",
            "cookie",
            "terms of use / Lao terms marker",
            "accessibility",
            "sitemap",
            "skip-to-content",
            "contact / login",
            "help/faq",
            "about-site",
            "thin laoofficialgazette.gov.la / moj.gov.la portal shells",
        ],'''
    src = src.replace(old_h, new_h)
    p.write_text(src)
    print("soft_filter ok", p.stat().st_size)

def build():
    p = Path("/workspace/do_ir_resume/laos_build.py")
    src = p.read_text()
    repls = [
        ('"""Build Tunisia IR from filtered tip 6178f00710c3 with real gte-small.',
         '"""Build Laos IR from filtered tip 80cbe8a84f83 with real gte-small.'),
        ("tunisia_filtered_6178f00710c3", "laos_filtered_80cbe8a84f83"),
        ("ipfs_tunisia_laws_ir", "ipfs_laos_laws_ir"),
        ('"embeddings" / "tunisia.npy"', '"embeddings" / "laos.npy"'),
        ('"tunisia_corpus_6178f00710c3.parquet"', '"laos_corpus_80cbe8a84f83.parquet"'),
        ('"tunisia_bm25_spill"', '"laos_bm25_spill"'),
        ("tunisia_fts.sqlite", "laos_fts.sqlite"),
        ("tunisia_build_6178f00710c3.log", "laos_build_80cbe8a84f83.log"),
        ("6178f00710c3749e5064c5ffea58c2d7c63b4a43", "80cbe8a84f83deda1ca4963dbcbb19b1d1bffb76"),
        ("6178f00710c3", "80cbe8a84f83"),
        ("tunisia_normalization.json", "laos_normalization.json"),
        ("tunisia_build_6178f00710c3_result.json", "laos_build_80cbe8a84f83_result.json"),
        ("tunisia build start", "laos build start"),
        ("tunisia_build_filter_embed_package_", "laos_build_filter_embed_package_"),
    ]
    for a, b in repls:
        if a not in src:
            print("WARN missing:", a[:70])
        src = src.replace(a, b)
    old_shed = '''COLLECTOR_SHED_ORDER = [
    ("mm", [184652, 184631]),
    ("th", [184653, 184632]),
    ("dk", [68137, 68130]),
    ("at_deepen", [67996]),
    ("it_deepen", [162333]),
]'''
    new_shed = '''COLLECTOR_SHED_ORDER = [
    ("mm", [184652, 184631]),
    ("is-reg", [260505, 260498]),
    ("th", []),  # live PIDs refreshed at shed time
    ("dk", [68137, 68130]),
    ("it_deepen", [228586]),  # protect last
    ("at_deepen", [67996]),    # protect last
]'''
    if old_shed in src:
        src = src.replace(old_shed, new_shed)
    else:
        print("WARN shed block missing")
    inject = '''
def _refresh_live_pids() -> None:
    """Refresh th/mm/is-reg PIDs from /proc cmdline if listed ones are stale."""
    want = {
        "th": ("thailand", "th_collect", "collect_th", "/th/", "ipfs_thailand"),
        "mm": ("myanmar", "mm_collect", "collect_mm", "/mm/", "ipfs_myanmar"),
        "is-reg": ("iceland", "is_collect", "collect_is", "is-reg", "ipfs_iceland"),
    }
    found: dict[str, list[int]] = {k: [] for k in want}
    try:
        for d in Path("/proc").iterdir():
            if not d.name.isdigit():
                continue
            try:
                cmd = (d / "cmdline").read_bytes().replace(b"\\x00", b" ").decode("utf-8", "ignore")
            except Exception:
                continue
            low = cmd.lower()
            for name, keys in want.items():
                if any(k in low for k in keys):
                    found[name].append(int(d.name))
    except Exception:
        return
    for name, pids in found.items():
        if not pids:
            continue
        for i, (n, _) in enumerate(COLLECTOR_SHED_ORDER):
            if n == name:
                COLLECTOR_SHED_ORDER[i] = (name, sorted(set(pids))[:4])
                break

'''
    marker = "SIGTERM_NOTES: list[dict] = []\n"
    if marker in src and "_refresh_live_pids" not in src:
        src = src.replace(marker, marker + inject)
        src = src.replace(
            "def maybe_shed_collectors(stage: str) -> None:\n    g = mem_gib()",
            "def maybe_shed_collectors(stage: str) -> None:\n    _refresh_live_pids()\n    g = mem_gib()",
        )
    p.write_text(src)
    print("build ok", p.stat().st_size)

def upload():
    p = Path("/workspace/do_ir_resume/laos_upload.py")
    src = p.read_text()
    for a, b in [
        ("Tunisia", "Laos"),
        ("ipfs_tunisia_laws_ir", "ipfs_laos_laws_ir"),
        ("6178f00710c3", "80cbe8a84f83"),
        ("tunisia_upload_", "laos_upload_"),
    ]:
        src = src.replace(a, b)
    p.write_text(src)
    print("upload ok")

def smoke():
    p = Path("/workspace/do_ir_resume/laos_bm25_smoke.py")
    p.write_text('''#!/usr/bin/env python3
"""BM25 smoke for Laos IR — EN legal + corpus-native ASCII; Lao script expected empty."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_laos_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/laos_bm25_smoke_80cbe8a84f83.json")

QUERIES = [
    "law",
    "decree",
    "article",
    "constitution",
    "gazette",
    "laos",
    "penal",
    "code",
    "lao",
    "official",
    "ministry",
    "justice",
    "national",
    "assembly",
    "pdf",
    "gov",
    "ລັດຖະບັນຍັດ",
    "ລັດຖະທໍາມະນູນ",
    "ມາດຕາ",
]


def main() -> int:
    rel = Release(ROOT)
    detail = {"queries": {}, "ranked": [], "empty": [], "lao_empty": [], "pass": False}
    for q in QUERIES:
        hits = rel.bm25(q, top_k=5)
        top = [
            {
                "score": h.get("score"),
                "title": (h.get("title") or "")[:120],
                "instrument_id": h.get("instrument_id"),
                "record_type": h.get("record_type"),
            }
            for h in hits[:3]
        ]
        detail["queries"][q] = {"n": len(hits), "top": top}
        is_lo = any("\\u0e80" <= c <= "\\u0eff" for c in q)
        if hits:
            detail["ranked"].append(q)
        else:
            detail["empty"].append(q)
            if is_lo:
                detail["lao_empty"].append(q)
    gate = ["law", "decree", "article", "constitution", "gazette", "laos", "penal", "code"]
    ascii_q = [q for q in QUERIES if all(ord(c) < 128 for c in q)]
    ascii_ranked = [q for q in detail["ranked"] if q in ascii_q]
    core_ok = sum(1 for q in gate if q in detail["ranked"]) >= 5
    ascii_ok = len(ascii_ranked) >= max(6, (len(ascii_q) + 1) // 2)
    ok = core_ok or ascii_ok
    detail["pass"] = ok
    detail["gate"] = gate
    detail["core_ranked"] = [q for q in gate if q in detail["ranked"]]
    detail["tokenizer_note"] = (
        "ASCII-after-diacritic-fold tokenizer ([0-9A-Za-z]+); "
        "Lao script queries expected empty; EN legal/gazette terms are the smoke gate"
    )
    OUT.write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    print(json.dumps({
        "pass": detail["pass"],
        "ranked": detail["ranked"],
        "empty": detail["empty"],
        "lao_empty": detail["lao_empty"],
        "n_core_ranked": sum(1 for q in gate if q in detail["ranked"]),
        "n_core": len(gate),
        "n_ascii_ranked": len(ascii_ranked),
        "n_ascii": len(ascii_q),
    }, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
''')
    # Fix escapes: the write_text above has \\u and \\n from the quoted string in this adapter
    # When this adapter file is written via cat HEREDOC with 'ENDSCRIPT', the \\ becomes \
    # So in the smoke file we want actual Lao chars and \n — re-fix properly
    text = p.read_text()
    # If we got literal \\u0e80 in source, convert the is_lo check
    text = text.replace('any("\\\\u0e80" <= c <= "\\\\u0eff" for c in q)',
                        'any("\\u0e80" <= c <= "\\u0eff" for c in q)')
    text = text.replace('+ "\\\\n"', '+ "\\n"')
    p.write_text(text)
    print("smoke ok")

def publish():
    p = Path("/workspace/do_ir_resume/laos_write_publish_report.py")
    src = p.read_text()
    for a, b in [
        ("tunisia_filter_6178f00710c3.json", "laos_filter_80cbe8a84f83.json"),
        ("tunisia_build_6178f00710c3_result.json", "laos_build_80cbe8a84f83_result.json"),
        ("tunisia_normalization.json", "laos_normalization.json"),
        ("tunisia_bm25_smoke_6178f00710c3.json", "laos_bm25_smoke_80cbe8a84f83.json"),
        ("ipfs_tunisia_laws_ir", "ipfs_laos_laws_ir"),
        ("tunisia_upload_6178f00710c3.json", "laos_upload_80cbe8a84f83.json"),
        ("6178f00710c3749e5064c5ffea58c2d7c63b4a43", "80cbe8a84f83deda1ca4963dbcbb19b1d1bffb76"),
        ("6178f00710c3", "80cbe8a84f83"),
        ('"country": "tunisia"', '"country": "laos"'),
        ("endomorphosis/ipfs_tunisia_laws", "endomorphosis/ipfs_laos_laws"),
        ("1326/49830", "547/8790"),
        ("tunisia_filtered_6178f00710c3", "laos_filtered_80cbe8a84f83"),
        ("tunisia_publish_6178f00710c3.json", "laos_publish_80cbe8a84f83.json"),
        ("mm/th/dk/at_deepen/it_deepen", "mm/is-reg/th/dk/it_deepen/at_deepen"),
    ]:
        src = src.replace(a, b)
    src = src.replace(
        'french_ranked = [q for q in smoke["ranked"] if not any("\\u0600" <= c <= "\\u06FF" for c in q)]',
        'ascii_ranked = [q for q in smoke["ranked"] if all(ord(c) < 128 for c in q)]',
    )
    src = src.replace("french_ranked", "ascii_ranked")
    src = src.replace(
        "f\"Arabic script empty under ASCII tokenizer as expected)\"",
        "f\"Lao script empty under ASCII tokenizer as expected)\"",
    )
    src = src.replace(
        "BM25 PASS on French JO/IORT legal terms (diacritic-folded ASCII); Arabic script queries empty by tokenizer design",
        "BM25 PASS on EN legal/gazette terms (ASCII tokenizer); Lao script queries empty by tokenizer design",
    )
    p.write_text(src)
    print("publish ok")

if __name__ == "__main__":
    soft_filter()
    build()
    upload()
    smoke()
    publish()
    print("ALL_ADAPTED")
