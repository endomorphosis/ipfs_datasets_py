"""HF-import (staging/national/<CC>/iso_<CC>.hf<ts>pNNNN.jsonl) parsing, provenance and cross-lane dedupe.

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_hf_import.py  (synthetic data in /tmp only)
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import pyarrow.parquet as pq  # noqa: E402
import run_loop  # noqa: E402
import schema as S  # noqa: E402
from test_hold_policy import _tmp, base, run, w  # noqa: E402

TXT = "Article 1. " + "Le présent arrêté règle la matière visée à l'article 78 de la Constitution. " * 6
HF = {"source": "hf:endomorphosis/ipfs_belgium_laws", "source_revision": "edb77b1", "hf_dataset":
      "endomorphosis/ipfs_belgium_laws", "license_note": "Moniteur belge official publications"}


def nat(doc_id, place="iso:BE", **kw):
    return base(doc_id, place_id=place, country_code="BE", doc_type="statute", language="fr", **kw)


def test_batch_order_parses_hf_suffix():
    a = run_loop.batch_order(".hf20261012T103649Zp0038", 0.0, "x")
    b = run_loop.batch_order(".hf20261012T103649Zp0002", 0.0, "y")
    c = run_loop.batch_order(".hf20261012T113000Zp0001", 0.0, "z")
    assert a[4] == "name" and a[1] == 38 and b[1] == 2
    assert a[0] == b[0] and b[:2] < a[:2] < c[:2]          # same batch: part order; newer batch later
    assert run_loop.batch_order(".20261011T003234Zp0001", 0, "")[1] == 1
    assert run_loop.batch_order(".pldz_KPLBWP_archive_b00051_20261012T104607Zp0001", 0, "")[1] == 1
    m = run_loop._FNAME.match("iso_GB.hf20261012T103649Zp0038.jsonl")
    assert m and m.group("key") == "iso_GB"


def test_parts_all_kept_newer_batch_wins_provenance():
    tmp = _tmp()
    try:
        d = tmp / "staging/national/BE"
        # same batch, 3 parts written out of order (mtime) -> every doc of every part kept
        w(d / "iso_BE.hf20261012T100000Zp0002.jsonl", [nat("b2", text=TXT + "2", html=None, **HF)], mtime=1_700_000_300)
        w(d / "iso_BE.hf20261012T100000Zp0001.jsonl", [nat("b1", **HF), nat("x", title_native="old", **HF)],
          mtime=1_700_000_400)
        w(d / "iso_BE.hf20261012T100000Zp0003.jsonl", [nat("b3", **HF)], mtime=1_700_000_100)
        # newer batch re-imports x -> newer wins (even though its mtime is older)
        w(d / "iso_BE.hf20261012T110000Zp0001.jsonl", [nat("x", title_native="new", **HF)], mtime=1_699_000_000)
        scratch, summ = run(tmp, **{"national-repo": "test/nat"})
        rows = pq.read_table(scratch / "out_national" / S.ROOT / "data/BE/iso_BE_html.parquet").to_pylist()
        by = {r["doc_id"]: r for r in rows}
        assert sorted(by) == ["b1", "b2", "b3", "x"], sorted(by)
        assert by["x"]["title_native"] == "new"
        assert by["b1"]["license_note"] == "Moniteur belge official publications"
        em = json.loads(by["b1"]["extra_metadata"])
        assert em["source"] == HF["source"] and em["hf_dataset"] == HF["hf_dataset"]
        assert em["source_revision"] == "edb77b1"
        assert summ["ts_from_name"] == 4 and summ.get("dedupe_cross_lane_dropped", 0) == 0
        assert summ.get("dedupe_cid_collision_replaced", 0) == 1  # x staged twice under the same CID
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cross_lane_dedupe_keeps_primary():
    tmp = _tmp()
    try:
        # EU bot primary records (different place_key -> different CID)
        w(tmp / "staging/eu/BE/iso_BE-VLG.20261012T090000Zp0001.jsonl", [
            nat("eu_url", place="iso:BE-VLG", source_url="https://www.ejustice.just.fgov.be/eli/loi/2020/1"),
            nat("eu_txt", place="iso:BE-VLG", text=TXT, html=None, adopted_date="2020-01-02",
                source_url="https://eu.example/a"),
            nat("eu_eli", place="iso:BE-VLG", eli="ELI/loi/2019/7", source_url="https://eu.example/b"),
            nat("eu_short", place="iso:BE-VLG", text="Banque de données Justel", html=None,
                source_url="https://eu.example/c"),
        ])
        w(tmp / "staging/national/BE/iso_BE.hf20261012T100000Zp0001.jsonl", [
            nat("hf_url", source_url="http://ejustice.just.fgov.be/eli/loi/2020/1/", **HF),     # same URL
            nat("hf_txt", text="  " + TXT.upper().replace(" ", "\n "), html=None, adopted_date="2020-01-02",
                source_url="https://hf.example/a", **HF),                                        # same text+date
            nat("hf_eli", extra_metadata={"eli": "eli/loi/2019/7"}, source_url="https://hf.example/b", **HF),
            nat("hf_similar", text=TXT + " Article 2.", html=None, adopted_date="2020-01-02",
                source_url="https://hf.example/c", **HF),                                        # merely similar
            nat("hf_txt_other_date", text=TXT, html=None, adopted_date="1999-01-01", title_native="other",
                source_url="https://hf.example/d", **HF),                                        # same text, nothing else
            nat("hf_short", text="Banque de données Justel", html=None, source_url="https://hf.example/e", **HF),
        ])
        # a non-import national record with the same URL is never dropped
        w(tmp / "staging/national/BE/iso_BE.20261012T100000Zp0001.jsonl", [
            nat("own", source_url="https://www.ejustice.just.fgov.be/eli/loi/2020/1")])
        scratch, summ = run(tmp, **{"national-repo": "test/nat"})
        nd = scratch / "out_national" / S.ROOT / "data/BE"
        kept = {r["doc_id"] for r in pq.read_table(nd / "iso_BE_html.parquet").to_pylist()}
        eu = {r["doc_id"] for r in pq.read_table(nd / "iso_BE-VLG_html.parquet").to_pylist()}
        assert eu == {"eu_url", "eu_txt", "eu_eli", "eu_short"}
        assert kept == {"hf_similar", "hf_txt_other_date", "hf_short", "own"}, kept
        assert summ["dedupe_cross_lane_dropped"] == 3
        pc = summ["per_country"]["BE"]
        assert pc["dedupe_cross_lane_by_source_url"] == 1 and pc["dedupe_cross_lane_by_text_hash"] == 1
        assert pc["dedupe_cross_lane_by_official_id"] == 1
        logs = list((tmp / "quarantine").rglob("*.dedupe.jsonl")) + list(scratch.rglob("*.dedupe.jsonl"))
        recs = [json.loads(l) for p in logs for l in p.read_text().splitlines()]
        assert {r["doc_id"] for r in recs} == {"hf_url", "hf_txt", "hf_eli"}
        assert all(r["kept_primary"].startswith("iso_BE-") for r in recs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
