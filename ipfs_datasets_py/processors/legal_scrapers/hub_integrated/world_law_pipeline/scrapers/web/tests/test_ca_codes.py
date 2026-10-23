"""CA crawler: place codes from place_codes.parquet and staged file names (no network)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import importlib.util, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ca", HERE / "ca_bylaw_crawler.py")
ca = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ca)


def _sample_rec(t: dict) -> dict:
    return {
        "place_id": t["place_id"], "requested_url": t["homepage"] + "bylaw-1.pdf",
        "doc_url": t["homepage"] + "bylaw-1.pdf",
        "title": "By-law No. 2020-15 Noise", "content_type": "pdf",
        "text": "The Council enacts as follows. Section 1 ...",
        "fetched_at": "2026-10-13T16:00:00Z", "municipality_name": t["name"], "qid": t["qid"],
        "insee_code": t["insee_code"], "place_code_system": t.get("place_code_system"),
        "source_url": t["source_url"], "homepage": t["homepage"],
    }


def test_codes_and_naming():
    ts = ca.load_targets()
    have = [t for t in ts if t["insee_code"]]
    by_sys = {}
    for t in have:
        by_sys[t["place_code_system"]] = by_sys.get(t["place_code_system"], 0) + 1
    print(f"targets={len(ts)} with_code={len(have)} ({100*len(have)/max(1,len(ts)):.1f}%) "
          + " ".join(f"{k}={v}" for k, v in sorted(by_sys.items())))
    assert len(have) / len(ts) > 0.9
    for t in have[:5]:
        assert ca.place_key(t["place_id"]) == "wd_" + t["place_id"].split(":")[1]
        assert ca.base.place_key(t["place_id"]) == ca.place_key(t["place_id"])
        rec = ca.to_schema_record(_sample_rec(t), 0)
        assert rec["place_code"] == t["insee_code"]
        assert rec["place_code_system"] == t["place_code_system"]
        assert rec["country_code"] == "CA"
        # CD codes must never be labelled as CSD
        if t["place_code_system"] == "ca_sgc_csd":
            assert len(str(t["insee_code"])) == 7
        if t["place_code_system"] == "ca_sgc_cd":
            assert len(str(t["insee_code"])) == 4
        errs = ca.base.world_schema.validate_record(rec)
        assert not errs, errs
        print(t["place_id"], t["name"], t["insee_code"], t["place_code_system"],
              "->", f"CA/{ca.place_key(t['place_id'])}.full.<UTCts>.jsonl")
    assert ca.OUT == ca.base.OUT == Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/web/CA"))

    by_id = {t["place_id"]: t for t in ts}

    toronto = by_id["wd:Q172"]
    assert toronto["insee_code"] == "3520005"
    assert toronto["place_code_system"] == "ca_sgc_csd"
    rec = ca.to_schema_record(_sample_rec(toronto), 0)
    assert rec["place_code"] == "3520005" and rec["place_code_system"] == "ca_sgc_csd"
    assert not ca.base.world_schema.validate_record(rec)
    print("Toronto", toronto["insee_code"], toronto["place_code_system"], "ok")

    peel = by_id["wd:Q50811"]
    assert peel["insee_code"] == "3521"
    assert peel["place_code_system"] == "ca_sgc_cd"
    rec = ca.to_schema_record(_sample_rec(peel), 0)
    assert rec["place_code"] == "3521" and rec["place_code_system"] == "ca_sgc_cd"
    assert not ca.base.world_schema.validate_record(rec)
    print("Peel", peel["insee_code"], peel["place_code_system"], "ok")

    metro_van = by_id["wd:Q1061069"]
    assert metro_van["insee_code"] == "5915"
    assert metro_van["place_code_system"] == "ca_sgc_cd"
    rec = ca.to_schema_record(_sample_rec(metro_van), 0)
    assert rec["place_code"] == "5915" and rec["place_code_system"] == "ca_sgc_cd"
    assert not ca.base.world_schema.validate_record(rec)
    print("Metro Vancouver", metro_van["insee_code"], metro_van["place_code_system"], "ok")

    # No CD (4-digit) code may sit under ca_sgc_csd in the map
    for pid, meta in ca._CODE_MAP.items():
        if meta["code_system"] == "ca_sgc_csd":
            assert len(meta["code"]) == 7, (pid, meta)
        if meta["code_system"] == "ca_sgc_cd":
            assert len(meta["code"]) == 4, (pid, meta)


if __name__ == "__main__":
    test_codes_and_naming(); print("ok")
