#!/usr/bin/env python3
"""Village (sołectwo/miejscowość) lists for same-name PL gminas, from Polish Wikipedia articles (public, robots-checked,
~1 req/s, project UA). Used only to disambiguate ambiguous unmatched docs (Czarna x3, Świętajno, Radzanów, ...).
Cache: staging/eu/_state/pl/wiki_villages.json  {teryt7: {"title":..., "villages":[...], "url":...}}"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, re, sys, urllib.parse
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from common.live import PoliteSession, get_logger, atomic_write  # noqa
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/pl/wiki_villages.json"))
log = get_logger("pl_gmina_villages")

def fetch(sess, title):
    u = "https://pl.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="")
    r = sess.get(u, ok=(200, 404))
    return (u, r.text) if r.status_code == 200 else (u, None)

def villages(html):
    # links inside the "Sołectwa" / "Miejscowości" sections only (neighbouring gminas are listed elsewhere)
    secs = re.split(r'<h2 id="', html)
    body = " ".join(x for x in secs if re.match(r"(So[łl]ectwa|Miejscowo|Miejscowości|Podzia[łl])", x))
    out = []
    for t in re.findall(r'<a rel="mw:WikiLink" href="[^"]*/wiki/[^":#]+" title="([^"]+)"', body):
        t = re.sub(r"\s*\(.*\)$", "", t)
        if ":" not in t and len(t) < 40 and t[0].isupper():
            out.append(t)
    return sorted(set(out))


def main(pairs):
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    sess = PoliteSession(log, min_interval=1.5)
    for teryt, name, powiat_adj in pairs:
        if teryt in cache:
            continue
        for title in (f"Gmina {name} (powiat {powiat_adj})", f"Gmina {name}"):
            u, h = fetch(sess, title)
            if h and "powiat " + powiat_adj in h:
                cache[teryt] = {"title": title, "url": u, "villages": villages(h)}
                log.info("%s %s: %d links", teryt, title, len(cache[teryt]["villages"]))
                break
        else:
            cache[teryt] = {"title": None, "villages": []}
            log.info("%s %s: no article", teryt, name)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp"); tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=0)); tmp.replace(OUT)

if __name__ == "__main__":
    pairs = [l.split("\t") for l in sys.stdin.read().strip().splitlines()]
    main(pairs)
