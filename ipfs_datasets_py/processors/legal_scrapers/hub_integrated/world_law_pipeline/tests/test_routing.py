"""Repo routing: iso_* places -> national repo/out tree, everything else -> municipal (synthetic data in /tmp only)."""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import pyarrow.parquet as pq  # noqa: E402
import schema as S  # noqa: E402
from test_hold_policy import _tmp, base, run, w  # noqa: E402
import schema as _S  # noqa: E402
_S.BUCKETED_COUNTRIES = frozenset()  # flat-layout tests; hash buckets: test_buckets.py


def test_iso_places_route_to_national():
    tmp = _tmp()
    try:
        w(tmp / "staging/eu/FR/iso_FR.20261011T010000Zp0001.jsonl",
          [base("n1", place_id="iso:FR", country_code="FR", doc_type="statute", language="fr")])
        w(tmp / "staging/eu/ES/iso_ES-CT.20261011T010000Zp0001.jsonl",
          [base("n2", place_id="iso:ES-CT", country_code="ES", doc_type="statute", language="es")])
        w(tmp / "staging/eu/FR/wd_Q90.20261011T010000Zp0001.jsonl",
          [base("m1", place_id="wd:Q90", country_code="FR", language="fr")])
        # pre-existing national file in the real national out tree is merged (and never written through)
        nat_old = tmp / "out_national" / S.ROOT / "data/FR"
        nat_old.mkdir(parents=True)
        scratch, summ = run(tmp, **{"repo": "test/muni", "national-repo": "test/nat"})
        mun, nat = scratch / "out" / S.ROOT, scratch / "out_national" / S.ROOT
        assert sorted(p.name for p in (mun / "data").glob("*/*.parquet")) == ["wd_Q90_html.parquet"]
        assert sorted(p.name for p in (nat / "data").glob("*/*.parquet")) == ["iso_ES-CT_html.parquet", "iso_FR_html.parquet"]
        assert pq.read_table(str(mun / "places.parquet")).column("place_key").to_pylist() == ["wd_Q90"]
        assert sorted(pq.read_table(str(nat / "places.parquet")).column("place_key").to_pylist()) == ["iso_ES-CT", "iso_FR"]
        pm = [json.loads(x) for x in (scratch / "planned_commit.jsonl").read_text().splitlines()]
        pn = [json.loads(x) for x in (scratch / "planned_commit_national.jsonl").read_text().splitlines()]
        assert {x["repo"] for x in pm} == {"test/muni"} and {x["repo"] for x in pn} == {"test/nat"}
        assert not any("iso_" in x["path_in_repo"] for x in pm)
        assert all("wd_Q90" not in x["path_in_repo"] for x in pn)
        assert "World National Law" in (scratch / "out_national" / "README.md").read_text()
        assert "world_national_law" in (scratch / "out" / "README.md").read_text()
        assert summ["places_written_by_repo"] == {"test/muni": 1, "test/nat": 2}
        assert not (tmp / "out_national" / S.ROOT / "data/FR/iso_FR_html.parquet").exists()  # real tree untouched
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_national_only_run_does_not_touch_municipal():
    tmp = _tmp()
    try:
        w(tmp / "staging/eu/FR/iso_FR.20261011T010000Zp0001.jsonl",
          [base("n1", place_id="iso:FR", country_code="FR", doc_type="statute", language="fr")])
        scratch, summ = run(tmp, **{"repo": "test/muni", "national-repo": "test/nat"})
        assert not (scratch / "planned_commit.jsonl").exists()
        assert (scratch / "planned_commit_national.jsonl").exists()
        assert summ.get("files_to_upload", 0) == 0 and summ["national_files_to_upload"] > 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_is_national_key():
    assert S.is_national_key("iso_FR") and S.is_national_key("iso_US-CA") and S.is_national_key("iso_EU")
    assert not S.is_national_key("wd_Q90") and not S.is_national_key("1008538")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
