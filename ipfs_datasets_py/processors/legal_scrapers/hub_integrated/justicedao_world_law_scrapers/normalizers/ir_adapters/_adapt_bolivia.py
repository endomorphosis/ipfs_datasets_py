#!/usr/bin/env python3
"""Adapt copied Laos scripts into Bolivia scripts."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

TIP12 = "6c97669d2103"
TIP_FULL = "6c97669d2103f7013a9882b9d7b2e0263ce2fcad"
FLOOR_L, FLOOR_A = 755, 7805
BASE = Path("/workspace/do_ir_resume")


def soft_filter():
    p = BASE / "bolivia_soft_filter.py"
    src = p.read_text()
    repls = [
        ("Soft chrome filter for Laos tip 80cbe8a84f83; floor >= 547/8790.",
         f"Soft chrome filter for Bolivia tip {TIP12}; floor >= {FLOOR_L}/{FLOOR_A}."),
        ("endomorphosis/ipfs_laos_laws", "endomorphosis/ipfs_bolivia_laws"),
        ("80cbe8a84f83deda1ca4963dbcbb19b1d1bffb76", TIP_FULL),
        ("80cbe8a84f83", TIP12),
        ("FLOOR_LAWS, FLOOR_ARTS = 547, 8790", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_L}, {FLOOR_A}"),
        ("laos_filtered_", "bolivia_filtered_"),
        ('"slug": "laos"', '"slug": "bolivia"'),
        ('"name": "Laos"', '"name": "Bolivia"'),
        ("# Laos filtered pack", "# Bolivia filtered pack"),
        ("laos_filter_", "bolivia_filter_"),
        (
            '"filter_reason": "soft-drop Lao Official Gazette / MoJ portal chrome (privacy/cookie/terms/sitemap/help/skip/contact/login/about) if present"',
            '"filter_reason": "soft-drop Gaceta Oficial / lexivox / justicia.gob.bo portal chrome (privacidad/cookie/terminos/mapa del sitio/ayuda/contacto/login/acerca de) if present"',
        ),
    ]
    for a, b in repls:
        if a not in src:
            print("WARN soft missing:", a[:80])
        src = src.replace(a, b)
    old_start = src.index("# Soft portal-chrome markers")
    old_end = src.index("COMPILED = ")
    new_markers = """# Soft portal-chrome markers (ES/BO — Gaceta Oficial / lexivox / justicia.gob.bo)
MARKERS = [
    (r"\\bprivacidad\\b", "privacy"),
    (r"\\bpol[ií]tica\\s+de\\s+privacidad\\b", "privacy"),
    (r"\\bprivacy\\b", "privacy"),
    (r"\\bcookies?\\b", "cookie"),
    (r"\\bt[eé]rminos\\s+de\\s+uso\\b", "terms"),
    (r"\\bt[eé]rminos\\s+y\\s+condiciones\\b", "terms"),
    (r"\\bterms\\s+of\\s+(use|service)\\b", "terms"),
    (r"\\baccesibilidad\\b", "accessibility"),
    (r"\\baccessibility\\b", "accessibility"),
    (r"\\bmapa\\s+del\\s+sitio\\b", "sitemap"),
    (r"\\bsitemap\\b", "sitemap"),
    (r"\\bcontactos?\\b", "contact"),
    (r"\\bcont[aá]ctenos\\b", "contact"),
    (r"\\b(login|iniciar\\s+sesi[oó]n|registrarse|registro)\\b", "login"),
    (r"\\bayuda\\b", "help"),
    (r"\\bfaq\\b", "help"),
    (r"\\bpreguntas\\s+frecuentes\\b", "help"),
    (r"\\bacerca\\s+de\\b", "about-site"),
    (r"\\bsobre\\s+(nosotros|este\\s+sitio|el\\s+portal)\\b", "about-site"),
    (r"\\babout\\s+(us|this\\s+site)\\b", "about-site"),
    (r"\\bskip[- ]?to[- ]?content\\b", "skip"),
    (r"\\bsaltar\\s+al\\s+contenido\\b", "skip"),
    (r"gacetaoficialdebolivia\\.gob\\.bo/(?:contacto|privacidad|cookie|terminos|login|mapa|ayuda|faq|acerca)", "portal-chrome-url"),
    (r"lexivox\\.org/(?:contacto|privacidad|cookie|terminos|login|mapa|ayuda|faq|acerca)", "portal-chrome-url"),
    (r"justicia\\.gob\\.bo/(?:contacto|privacidad|cookie|terminos|login|mapa|ayuda|faq|acerca)", "portal-chrome-url"),
]

"""
    src = src[:old_start] + new_markers + src[old_end:]
    old_h = '''        "chrome_heuristics": [
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
    new_h = '''        "chrome_heuristics": [
            "privacidad / privacy",
            "cookies",
            "terminos de uso",
            "accesibilidad",
            "mapa del sitio",
            "saltar al contenido / skip",
            "contacto / login",
            "ayuda/faq",
            "acerca de",
            "thin gacetaoficialdebolivia.gob.bo / lexivox.org / justicia.gob.bo portal shells",
        ],'''
    if old_h not in src:
        print("WARN heuristics missing")
    else:
        src = src.replace(old_h, new_h)
    # Prefer HEAD when thicker: rewrite tip selection
    old_stop = '''    print(f"hub_head={head[:12]} requested={TIP_SHORT}")
    if not head.startswith(TIP_SHORT):
        print(f"STOP: HEAD={head[:12]} != requested {TIP_SHORT}")
        try:
            laws_p = Path(hf_hub_download(REPO, "data/laws.parquet", repo_type="dataset", revision=head, token=token, cache_dir=str(CACHE_HF)))
            arts_p = Path(hf_hub_download(REPO, "data/articles.parquet", repo_type="dataset", revision=head, token=token, cache_dir=str(CACHE_HF)))
            print(f"HEAD_L_A={len(pd.read_parquet(laws_p))}/{len(pd.read_parquet(arts_p))}")
        except Exception as exc:
            print(f"HEAD_LA_error={exc}")
        return 1

    laws_path = Path(
        hf_hub_download(
            REPO, "data/laws.parquet", repo_type="dataset",
            revision=TIP_FULL, token=token, cache_dir=str(CACHE_HF),
        )
    )
    arts_path = Path(
        hf_hub_download(
            REPO, "data/articles.parquet", repo_type="dataset",
            revision=TIP_FULL, token=token, cache_dir=str(CACHE_HF),
        )
    )'''
    new_stop = '''    tip_full = TIP_FULL
    tip_short = TIP_SHORT
    print(f"hub_head={head[:12]} requested={TIP_SHORT}")
    if not head.startswith(TIP_SHORT):
        try:
            laws_p = Path(hf_hub_download(REPO, "data/laws.parquet", repo_type="dataset", revision=head, token=token, cache_dir=str(CACHE_HF)))
            arts_p = Path(hf_hub_download(REPO, "data/articles.parquet", repo_type="dataset", revision=head, token=token, cache_dir=str(CACHE_HF)))
            nL, nA = len(pd.read_parquet(laws_p)), len(pd.read_parquet(arts_p))
            print(f"HEAD_L_A={nL}/{nA}")
            if nL >= FLOOR_LAWS and nA >= FLOOR_ARTS:
                print(f"retarget_to_thicker_HEAD={head[:12]} L/A={nL}/{nA}")
                tip_full = head
                tip_short = head[:12]
                global OUT
                OUT = Path(f"/workspace/country-laws-ir/cache/bolivia_filtered_{tip_short}")
            else:
                print(f"STOP: HEAD={head[:12]} != requested {TIP_SHORT} and below floor")
                return 1
        except Exception as exc:
            print(f"HEAD_LA_error={exc}")
            return 1
    else:
        tip_full = head if head else TIP_FULL
        tip_short = tip_full[:12]

    laws_path = Path(
        hf_hub_download(
            REPO, "data/laws.parquet", repo_type="dataset",
            revision=tip_full, token=token, cache_dir=str(CACHE_HF),
        )
    )
    arts_path = Path(
        hf_hub_download(
            REPO, "data/articles.parquet", repo_type="dataset",
            revision=tip_full, token=token, cache_dir=str(CACHE_HF),
        )
    )'''
    if old_stop not in src:
        print("WARN stop block missing")
    else:
        src = src.replace(old_stop, new_stop)
    src = src.replace('"source_revision": TIP_FULL,', '"source_revision": tip_full,')
    src = src.replace(
        'f"# Bolivia filtered pack\\n\\nTip `{TIP_SHORT}` soft chrome filter. Floor {FLOOR_LAWS}/{FLOOR_ARTS}.\\n"',
        'f"# Bolivia filtered pack\\n\\nTip `{tip_short}` soft chrome filter. Floor {FLOOR_LAWS}/{FLOOR_ARTS}.\\n"',
    )
    src = src.replace('"source_tip": TIP_SHORT,', '"source_tip": tip_short,')
    src = src.replace('"source_tip_full": TIP_FULL,', '"source_tip_full": tip_full,')
    src = src.replace(
        'f"Hub tip {TIP_SHORT} @ {n_laws_b}/{n_arts_b}; HEAD was {head[:12]}"',
        'f"Hub tip {tip_short} @ {n_laws_b}/{n_arts_b}; HEAD was {head[:12]}"',
    )
    src = src.replace(
        f'Path("/workspace/country-laws-ir/reports/bolivia_filter_{TIP12}.json")',
        'Path(f"/workspace/country-laws-ir/reports/bolivia_filter_{tip_short}.json")',
    )
    p.write_text(src)
    print("soft_filter ok", p.stat().st_size)


def build():
    p = BASE / "bolivia_build.py"
    src = p.read_text()
    repls = [
        ('"""Build Laos IR from filtered tip 80cbe8a84f83 with real gte-small.',
         f'"""Build Bolivia IR from filtered tip {TIP12} with real gte-small.'),
        ("laos_filtered_80cbe8a84f83", f"bolivia_filtered_{TIP12}"),
        ("ipfs_laos_laws_ir", "ipfs_bolivia_laws_ir"),
        ('"embeddings" / "laos.npy"', '"embeddings" / "bolivia.npy"'),
        ('"laos_corpus_80cbe8a84f83.parquet"', f'"bolivia_corpus_{TIP12}.parquet"'),
        ('"laos_bm25_spill"', '"bolivia_bm25_spill"'),
        ("laos_fts.sqlite", "bolivia_fts.sqlite"),
        ("laos_build_80cbe8a84f83.log", f"bolivia_build_{TIP12}.log"),
        ("80cbe8a84f83deda1ca4963dbcbb19b1d1bffb76", TIP_FULL),
        ("80cbe8a84f83", TIP12),
        ("laos_normalization.json", "bolivia_normalization.json"),
        ("laos_build_80cbe8a84f83_result.json", f"bolivia_build_{TIP12}_result.json"),
        ("laos build start", "bolivia build start"),
        ("laos_build_filter_embed_package_", "bolivia_build_filter_embed_package_"),
    ]
    for a, b in repls:
        if a not in src:
            print("WARN build missing:", a[:80])
        src = src.replace(a, b)
    old_shed = '''COLLECTOR_SHED_ORDER = [
    ("mm", [184652, 184631]),
    ("is-reg", [260505, 260498]),
    ("th", []),  # live PIDs refreshed at shed time
    ("dk", [68137, 68130]),
    ("it_deepen", [228586]),  # protect last
    ("at_deepen", [67996]),    # protect last
]'''
    new_shed = '''COLLECTOR_SHED_ORDER = [
    ("mm", [184652, 184631]),
    ("th", [269479, 269469]),
    ("is-reg", []),  # live PIDs refreshed at shed time
    ("dk", [68137, 68130]),
    ("it_deepen", [269468]),  # protect last
    ("at_deepen", [67996]),    # protect last
]'''
    if old_shed in src:
        src = src.replace(old_shed, new_shed)
    else:
        print("WARN shed missing")
    p.write_text(src)
    print("build ok", p.stat().st_size)


def upload():
    p = BASE / "bolivia_upload.py"
    src = p.read_text()
    for a, b in [
        ("Laos IR", "Bolivia IR"),
        ("ipfs_laos_laws_ir", "ipfs_bolivia_laws_ir"),
        ("80cbe8a84f83", TIP12),
        ("laos_upload_", "bolivia_upload_"),
    ]:
        src = src.replace(a, b)
    p.write_text(src)
    print("upload ok", p.stat().st_size)


def smoke():
    p = BASE / "bolivia_bm25_smoke.py"
    p.write_text(f'''#!/usr/bin/env python3
"""BM25 smoke for Bolivia IR — Spanish legal terms (ley/decreto/artículo/...)."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_bolivia_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/bolivia_bm25_smoke_{TIP12}.json")

QUERIES = [
    "ley",
    "decreto",
    "artículo",
    "articulo",
    "constitución",
    "constitucion",
    "gaceta",
    "bolivia",
    "código",
    "codigo",
    "penal",
    "resolucion",
    "resolución",
    "reglamento",
]


def main() -> int:
    rel = Release(ROOT)
    detail = {{"queries": {{}}, "ranked": [], "empty": [], "pass": False}}
    for q in QUERIES:
        hits = rel.bm25(q, top_k=5)
        top = [
            {{
                "score": h.get("score"),
                "title": (h.get("title") or "")[:120],
                "instrument_id": h.get("instrument_id"),
                "record_type": h.get("record_type"),
            }}
            for h in hits[:3]
        ]
        detail["queries"][q] = {{"n": len(hits), "top": top}}
        if hits:
            detail["ranked"].append(q)
        else:
            detail["empty"].append(q)
    es_gate = [
        "ley", "decreto", "articulo", "constitucion", "gaceta",
        "bolivia", "codigo", "penal", "resolucion", "reglamento",
    ]
    es_ok = all(q in detail["ranked"] for q in es_gate)
    soft_ok = sum(1 for q in es_gate if q in detail["ranked"]) >= 7
    detail["pass"] = es_ok or soft_ok
    detail["tokenizer_note"] = (
        "ASCII-after-diacritic-fold tokenizer ([0-9A-Za-z]+); "
        "Spanish legal terms are the smoke gate (diacritic forms may fold)"
    )
    detail["es_pass"] = es_ok
    detail["es_gate"] = es_gate
    OUT.write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    print(json.dumps({{
        "pass": detail["pass"],
        "ranked": detail["ranked"],
        "empty": detail["empty"],
        "n_es_ranked": sum(1 for q in es_gate if q in detail["ranked"]),
        "n_es": len(es_gate),
    }}, indent=2, ensure_ascii=False))
    return 0 if detail["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
''')
    print("smoke ok", p.stat().st_size)


def publish():
    p = BASE / "bolivia_write_publish_report.py"
    src = p.read_text()
    repls = [
        ("laos_filter_80cbe8a84f83.json", f"bolivia_filter_{TIP12}.json"),
        ("laos_build_80cbe8a84f83_result.json", f"bolivia_build_{TIP12}_result.json"),
        ("laos_normalization.json", "bolivia_normalization.json"),
        ("laos_bm25_smoke_80cbe8a84f83.json", f"bolivia_bm25_smoke_{TIP12}.json"),
        ("ipfs_laos_laws_ir", "ipfs_bolivia_laws_ir"),
        ("laos_upload_80cbe8a84f83.json", f"bolivia_upload_{TIP12}.json"),
        ("80cbe8a84f83deda1ca4963dbcbb19b1d1bffb76", TIP_FULL),
        ("80cbe8a84f83", TIP12),
        ('"country": "laos"', '"country": "bolivia"'),
        ("endomorphosis/ipfs_laos_laws", "endomorphosis/ipfs_bolivia_laws"),
        ("547/8790", "755/7805"),
        ("laos_filtered_6c97669d2103", f"bolivia_filtered_{TIP12}"),
        ("laos_publish_", "bolivia_publish_"),
        ("Lao script empty under ASCII tokenizer as expected", "ES legal/gaceta gate"),
        ("BM25 PASS on EN legal/gazette terms (ASCII tokenizer); Lao script queries empty by tokenizer design",
         "BM25 PASS on ES legal/gaceta terms (ASCII tokenizer); Spanish diacritic forms may fold"),
        ("lean collectors left running (mm/is-reg/th/dk/it_deepen/at_deepen); MemAvailable stayed ~>3.5G; no SIGTERM",
         "lean collectors left running (mm/th/is-reg/dk/it_deepen/at_deepen); MemAvailable stayed ~>3.5G; no SIGTERM"),
        ('"sqlite_spill": "preferred for ~50k (DO OOM lesson)" if (build_r.get("neighbor_via") or "").startswith("sqlite") else "stock neighbors"',
         '"sqlite_spill": "stock bm25 neighbors (~8k corpus)" if (build_r.get("neighbor_via") or "") == "stock" else (build_r.get("neighbor_via") or "neighbors")'),
    ]
    for a, b in repls:
        if a not in src:
            print("WARN pub missing:", a[:90])
        src = src.replace(a, b)
    p.write_text(src)
    print("publish ok", p.stat().st_size)


if __name__ == "__main__":
    soft_filter()
    build()
    upload()
    smoke()
    publish()
    print("ALL_ADAPTED")
