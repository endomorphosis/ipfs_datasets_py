from pathlib import Path

from ipfs_datasets_py.processors.web_archiving.common_crawl_integration import (
    CommonCrawlSearchEngine,
    _normalize_cc_jurisdiction,
    _ensure_common_crawl_source_checkout,
)


def test_normalize_cc_jurisdiction_treats_state_gov_domains_as_state() -> None:
    jurisdiction, state_code = _normalize_cc_jurisdiction("azsos.gov", "federal", None)

    assert jurisdiction == "state"
    assert state_code == "AZ"


def test_normalize_cc_jurisdiction_preserves_explicit_federal_hosts() -> None:
    jurisdiction, state_code = _normalize_cc_jurisdiction("va.gov", "federal", None)

    assert jurisdiction == "federal"
    assert state_code == "VA"


def test_search_domain_hf_redirects_stateish_domains_before_hf_lookup() -> None:
    engine = CommonCrawlSearchEngine.__new__(CommonCrawlSearchEngine)
    observed = {}

    class _FakeHF:
        def search(self, **kwargs):
            observed.update(kwargs)
            return [
                {
                    "url": "https://apps.azsos.gov/rules",
                    "timestamp": "20260325000000",
                }
            ]

    engine.hf_search = _FakeHF()
    engine._normalize_records = CommonCrawlSearchEngine._normalize_records

    records = engine._search_domain_hf("apps.azsos.gov", 5, None, jurisdiction="federal")

    assert records
    assert observed["jurisdiction"] == "state"
    assert observed["state_code"] == "AZ"
    assert records[0]["url"] == "https://apps.azsos.gov/rules"


def test_search_domain_local_uses_hf_remote_meta_when_local_assets_missing(monkeypatch, tmp_path) -> None:
    engine = CommonCrawlSearchEngine.__new__(CommonCrawlSearchEngine)
    observed = {}

    class _Result:
        records = [
            {
                "url": "https://www.revisor.mn.gov/statutes/cite/518.17",
                "timestamp": "20260417000000",
            }
        ]

    class _FakeApi:
        @staticmethod
        def search_domain_via_meta_indexes(domain, **kwargs):
            observed["domain"] = domain
            observed.update(kwargs)
            return _Result()

    engine.api = _FakeApi()
    engine.master_db_path = tmp_path / "missing-master.duckdb"
    engine._normalize_records = CommonCrawlSearchEngine._normalize_records

    records = engine._search_domain_local("www.revisor.mn.gov", 3, None, parquet_root=tmp_path / "missing-parquet")

    assert records[0]["url"] == "https://www.revisor.mn.gov/statutes/cite/518.17"
    assert observed["domain"] == "www.revisor.mn.gov"
    assert observed["hf_remote_meta"] is True
    assert observed["master_db"] is None
    assert observed["hf_meta_index_dataset"] == "Publicus/common_crawl_pointer_indices"
    assert observed["hf_pointer_dataset"] == "Publicus/common_crawl_pointers_by_collection"


def test_common_crawl_source_checkout_auto_clone(monkeypatch, tmp_path) -> None:
    import ipfs_datasets_py.processors.web_archiving.common_crawl_integration as module

    fake_module = tmp_path / "common_crawl_integration.py"
    fake_module.write_text("", encoding="ascii")
    observed = {}

    def _fake_run(cmd, **kwargs):
        observed["cmd"] = cmd
        target = Path(cmd[-1])
        target.mkdir(parents=True)
        (target / "__init__.py").write_text("", encoding="ascii")
        return object()

    monkeypatch.setattr(module, "__file__", str(fake_module))
    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    root = _ensure_common_crawl_source_checkout()

    assert root == tmp_path
    assert observed["cmd"][:3] == ["git", "clone", "--depth"]
    assert (tmp_path / "common_crawl_search_engine" / "__init__.py").exists()
