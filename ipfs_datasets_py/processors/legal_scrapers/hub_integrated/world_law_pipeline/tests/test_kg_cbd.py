"""KG-kg_cbd:<organ id> place ids (Kyrgyz councils without a Wikidata item): schema validation, place_key safety and
inverse, municipal routing, flat layout, end-to-end dry-run build, and place_additions rows (synthetic data in /tmp).

Run: /workspace/hf-venv/bin/python /workspace/world_law/pipeline/tests/test_kg_cbd.py
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import csv, json, shutil, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
PIPE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPE))
sys.path.insert(0, str(PIPE / "tests"))
sys.path.insert(0, str(PIPE / "codes"))
import pyarrow.parquet as pq  # noqa: E402
import schema as S  # noqa: E402
from test_hold_policy import _tmp, base, run, w  # noqa: E402

HEX = "6284b63e72a046e7a44c73502293fa91"
UUID = "00113528-03b5-40db-ab9f-c19b3728499a"


def errs(pid, cc="KG"):
    return S.validate_record(base("d1", place_id=pid, country_code=cc, language="ky"))


def test_validation_only_kg_and_organ_charset():
    for oid in (HEX, UUID, "0849", "108"):
        assert not [e for e in errs(f"KG-kg_cbd:{oid}") if "place_id" in e], (oid, errs(f"KG-kg_cbd:{oid}"))
    e = errs(f"KG-kg_cbd:{HEX}", cc="KZ")
    assert any(x.startswith("kg_cbd_place_id_non_kg") for x in e), e
    for bad in ("KG-kg_cbd:1001.001", "KG-kg_cbd:a_b", "KG-kg_cbd:", "KG-kg_cbd:a/b", "KG-kg_cbd:a:b",
                "KZ-kg_cbd:abc", "kg_cbd:abc", "KG-kg_cbd:abc def"):
        assert any(x.startswith("bad_place_id") for x in errs(bad)), bad
    assert S.kg_cbd_place_id(HEX) == f"KG-kg_cbd:{HEX}"
    for bad in ("1001.001", "a_b", "", "x/y"):
        try:
            S.kg_cbd_place_id(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    try:
        S.place_key("KG-kg_cbd:1001.001")
        raise AssertionError("dotted organ id must not get a place_key")
    except ValueError:
        pass


def test_place_key_safe_inverse_routing_layout():
    for oid in (HEX, UUID, "0849"):
        pid = f"KG-kg_cbd:{oid}"
        k = S.place_key(pid)
        assert k == f"KG-kg_cbd_{oid}" and S._PLACE_KEY_RE.match(k) and "/" not in k and "." not in k and ":" not in k
        assert S.place_id_from_key(k) == pid
        assert not S.is_national_key(k) and not S.is_bucketed("KG", k)
        assert S.html_path("KG", k) == f"world_law/data/KG/{k}_html.parquet"
        assert S.metadata_path("KG", k) == f"world_law/metadata/KG/{k}.json"
        assert S.place_dirs("data", "KG", k) == ["world_law/data/KG"] or S.place_dirs("data", "KG", k)[0] == "world_law/data/KG"
    assert S.place_id_from_key("wd_Q90") == "wd:Q90" and S.place_id_from_key("iso_US-CA") == "iso:US-CA"
    # the shard-suffix parser (key.rsplit(".s", 1)) never fires on these keys
    k = S.place_key(f"KG-kg_cbd:{UUID}")
    assert not (".s" in k and k.rsplit(".s", 1)[1].isdigit())
    # normalize: place_id derived from a key round-trips
    import normalize as N
    rows = N.us_html_rows_to_world([{"cid": "c", "doc_id": "1", "doc_order": 0, "html": "<p>x</p>"}],
                                   place_key=k, country_code="KG", place_id=None, gnis=None,
                                   source_platform="kg_cbd", source_url="https://cbd.minjust.gov.kg/1", language="ky")
    assert rows[0]["place_id"] == f"KG-kg_cbd:{UUID}"


def test_end_to_end_dry_run_routes_to_municipal():
    tmp = _tmp()
    try:
        k = f"KG-kg_cbd_{HEX}"
        w(tmp / f"staging/sasia_ru/KG/{k}.20261011T010000Zp0001.jsonl",
          [base(f"k{i}", place_id=f"KG-kg_cbd:{HEX}", country_code="KG", language="ky") for i in range(3)])
        scratch, summ = run(tmp, **{"repo": "test/muni", "national-repo": "test/nat"})
        mun = scratch / "out" / S.ROOT
        assert (mun / f"data/KG/{k}_html.parquet").exists(), sorted(p.name for p in mun.rglob("*"))
        meta = json.loads((mun / f"metadata/KG/{k}.json").read_text())
        assert meta["place_id"] == f"KG-kg_cbd:{HEX}" and meta["place_key"] == k and meta["country_code"] == "KG"
        assert pq.read_table(str(mun / "places.parquet")).column("place_key").to_pylist() == [k]
        pm = [json.loads(x) for x in (scratch / "planned_commit.jsonl").read_text().splitlines()]
        assert {x["repo"] for x in pm} == {"test/muni"} and any(k in x["path_in_repo"] for x in pm)
        nat = scratch / "planned_commit_national.jsonl"
        assert not nat.exists() or k not in nat.read_text()
        assert summ.get("rows_rejected", 0) == 0 and summ.get("rows_ok") == 3, summ
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_place_additions_rows_filtering():
    import build_place_additions as B
    tmp = Path(tempfile.mkdtemp(prefix="wl_kg_"))
    try:
        cols = ["aiyl_aimak_ru", "aiyl_aimak_ky", "cbd_issuing_body_id", "merged_from_body_ids", "id_scheme",
                "proposed_place_id", "cbd_organ_id", "cbd_name_ky_raw", "cbd_name_ru_raw", "parent_rayon",
                "parent_oblast", "parent_oblast_iso", "cbd_id_flag"]
        def row(oid, flag="", scheme="kg_cbd", ru="А айыл аймак", iso="KG-C", pid=None):
            return {"aiyl_aimak_ru": ru, "aiyl_aimak_ky": "", "cbd_issuing_body_id": oid, "merged_from_body_ids": "",
                    "id_scheme": scheme, "proposed_place_id": pid if pid is not None else f"KG-kg_cbd:{oid}",
                    "cbd_organ_id": oid, "cbd_name_ky_raw": "Ky name", "cbd_name_ru_raw": "Ru name",
                    "parent_rayon": "Р", "parent_oblast": "О", "parent_oblast_iso": iso, "cbd_id_flag": flag}
        rows = [row(HEX, "nonnumeric_hash"), row("0849"), row("1001.001"),
                row("e466e36b-fa38-4561-8f86-e63e3d8a947ab", "nonnumeric_hash_nonstandard"),
                row("amb1"), row("wdx", scheme=""), row("dup", pid="KG-kg_cbd:other"), row(UUID, iso="")]
        prop = tmp / "p.csv"
        with prop.open("w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=cols); wr.writeheader(); wr.writerows(rows)
        amb = tmp / "a.csv"
        amb.write_text("cbd_issuing_body_id,place_id\namb1,\n", encoding="utf-8")
        problems, st = [], {}
        import collections
        st = collections.Counter()
        out = B.kg_cbd_rows({f"KG-kg_cbd:{UUID}"}, problems, proposed=prop, ambiguous=amb, stats=st)
        assert [r["place_id"] for r in out] == [f"KG-kg_cbd:{HEX}", "KG-kg_cbd:0849"], out
        assert st["kg_cbd_rows"] == 7 and st["kg_cbd_skip_nonstandard"] == 1 and st["kg_cbd_skip_ambiguous"] == 1
        assert st["kg_cbd_skip_bad_organ_id"] == 1 and st["kg_cbd_skip_id_mismatch"] == 1 and st["kg_cbd_skip_duplicate"] == 1
        r = out[0]
        assert r["country_code"] == "KG" and r["official_code_system"] == "kg_cbd_body" and r["official_code"] == HEX
        assert r["qid"] == "" and r["iso_3166_2"] == "KG-C" and r["admin_level"] == "municipality"
        assert r["name_native"] == "Ky name" and set(r) == set(B.COLS)
        assert all(S.validate_record(base("x", place_id=x["place_id"], country_code="KG", language="ky")) == []
                   for x in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL KG-CBD TESTS PASSED")
