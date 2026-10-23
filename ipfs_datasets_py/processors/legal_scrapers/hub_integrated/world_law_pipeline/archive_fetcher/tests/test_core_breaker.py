"""fetch_best with the breaker open: Common Crawl only, Wayback-only items flagged deferred (no network)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, tempfile, time
from pathlib import Path
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from archive import ratelimit as rl, core
from archive.core import ArchiveFetcher, Capture, ArchivedDoc

def run():
    rl.RATE_DIR = Path(tempfile.mkdtemp(prefix="rltest_"))
    with rl._brk_locked() as b: b.update(state="open", last_probe=time.time(), opened_at=time.time())
    fx = ArchiveFetcher(cache_dir=tempfile.mkdtemp(), use_cc=False)
    called = []
    def fake_cc(cap):
        called.append(cap.source); raise core.ArchiveError("nope")
    fx.fetch_cc = fake_cc
    fx.fetch_wayback = lambda cap: (_ for _ in ()).throw(AssertionError("wayback must be skipped"))
    wb = Capture("wayback", "wayback", "20260101000000", "https://x.org/a", 200, None, None, None)
    cc = Capture("commoncrawl", "CC-MAIN-2026-39", "20250101000000", "https://x.org/a", 200, None, None, None)
    # 2026-10-18: nothing usable + Wayback skipped by the open breaker -> ArchiveDeferred (reason breaker_open), not None
    try:
        fx.fetch_best([wb, cc]); assert False
    except core.ArchiveDeferred as e:
        assert e.reason == "breaker_open" and e.families == ["wayback"] and e.retry_in > 0
    assert called == ["commoncrawl"] and fx.last_wb_deferred == 1
    called.clear()
    assert fx.fetch_best([wb, cc], raise_deferred=False) is None and fx.last_wb_deferred == 1
    assert fx.fetch_best([cc]) is None and fx.last_wb_deferred == 0       # CC-only miss stays a real miss
    try: fx.wb_captures("x.org"); assert False
    except core.ArchiveTransient: pass
    print("ok core breaker", dict(fx.stats))
run()
