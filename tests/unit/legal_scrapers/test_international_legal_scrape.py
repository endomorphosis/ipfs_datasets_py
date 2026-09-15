from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import (
    infer_canonical_legal_corpus_for_dataset_id,
    list_canonical_legal_corpora_by_branch,
    list_snapshot_legal_corpora,
)
from ipfs_datasets_py.processors.legal_scrapers.international.catalog import (
    get_snapshot_corpus,
    list_snapshot_corpora,
    snapshot_catalog_summary,
)
from ipfs_datasets_py.processors.legal_scrapers.international.harvest import (
    missing_catalog_collectors,
    rewrite_sandbox_source,
)
from ipfs_datasets_py.processors.legal_scrapers.international.api import (
    list_legal_sources,
    resolve_legal_source,
    scrape_legal_data,
)
from ipfs_datasets_py.processors.legal_scrapers.international.runtime import (
    PACKAGE_HARVESTED_ROOT,
    collector_path_for,
    load_instrument_records,
)
from ipfs_datasets_py.processors.legal_scrapers.international.scrape_state import (
    load_skip_keys,
    skip_keys_for_row,
    sync_published_scrape_state,
)
from ipfs_datasets_py.processors.legal_scrapers.legal_corpus import (
    CIDGenerator,
    DiscoveryProvider,
    FetchProvider,
    Parser,
    get_jurisdiction,
)


def test_rewrite_sandbox_source_injects_configurable_roots():
    source = '''
from pathlib import Path
ROOT = Path("/workspace/legal-corpora")
DE = Path("/workspace/legal-corpora/de")
TOKEN = Path("/home/box/.cache/huggingface/token")
SCRAPERS = Path("/workspace/legal_scrapers/scrapers")
'''
    rewritten = rewrite_sandbox_source(source)
    assert "/workspace/legal-corpora" not in rewritten
    assert "/home/box/.cache/huggingface/token" not in rewritten
    assert "ROOT = _CORPORA" in rewritten
    assert "_CORPORA / \"de\"" in rewritten
    assert "TOKEN = _HF_TOKEN_PATH" in rewritten
    assert "SCRAPERS = _SCRAPERS" in rewritten
    assert "IPFS_DATASETS_LEGAL_CORPORA_ROOT" in rewritten


def test_snapshot_catalog_covers_parked_endomorphosis_datasets():
    summary = snapshot_catalog_summary()
    entries = list_snapshot_corpora(include_aliases=True)
    canonical = list_snapshot_corpora(include_aliases=False)

    assert summary["dataset_count"] == 205
    assert summary["canonical_count"] >= 200
    assert any(entry.slug == "germany" and entry.quality == "production" for entry in canonical)
    assert get_snapshot_corpus("DE").canonical_slug == "germany"
    assert get_snapshot_corpus("dominicanrepublic").canonical_slug == "dominican_republic"
    assert get_snapshot_corpus("endomorphosis/ipfs_sweden_laws").source_dataset_id == "endomorphosis/ipfs_sweden_laws"
    assert len(entries) == 205


def test_unified_api_keeps_native_us_and_netherlands_handlers():
    netherlands = resolve_legal_source("NL")
    germany = resolve_legal_source("germany")
    federal = resolve_legal_source("us_code")

    assert netherlands.kind.startswith("native")
    assert netherlands.handler == "netherlands"
    assert germany.kind == "snapshot"
    assert germany.dataset_id == "endomorphosis/ipfs_germany_laws"
    assert germany.collector == "collect_gii.py"
    assert federal.handler == "us_code"
    native_keys = {source.key for source in list_legal_sources(include_snapshots=False)}
    assert {"us", "federal", "us_code", "state", "municipal", "recap", "netherlands"} <= native_keys


def test_canonical_registry_resolves_endomorphosis_dataset_ids():
    germany = infer_canonical_legal_corpus_for_dataset_id("endomorphosis/ipfs_germany_laws")
    sweden = infer_canonical_legal_corpus_for_dataset_id("endomorphosis/ipfs_sweden_laws")
    sweden_ir = infer_canonical_legal_corpus_for_dataset_id("justicedao/ipfs_sweden_laws_ir")

    assert germany.key == "germany_laws"
    assert germany.hf_dataset_id == "justicedao/ipfs_germany_laws"
    assert sweden.key == "sweden_laws"
    assert sweden.hf_dataset_id == "endomorphosis/ipfs_sweden_laws"
    assert sweden.country_codes == ("SE",)
    assert sweden_ir.key == "sweden_laws"
    eu_core = [corpus.key for corpus in list_canonical_legal_corpora_by_branch("eu")]
    assert eu_core == ["france_laws", "germany_laws", "netherlands_laws", "spain_laws"]
    snapshot_keys = {corpus.key for corpus in list_snapshot_legal_corpora()}
    assert "sweden_laws" in snapshot_keys
    assert "germany_laws" in snapshot_keys


def test_harvested_collect_gii_is_available_in_package():
    path = collector_path_for(get_snapshot_corpus("germany"))
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "/workspace/legal-corpora" not in text
    assert "collect_gii" in path.name


def test_all_catalog_collectors_are_harvested():
    missing = missing_catalog_collectors(dest_root=PACKAGE_HARVESTED_ROOT)
    assert missing == []
    later = [
        collector_path_for(get_snapshot_corpus("angola")),
        collector_path_for(get_snapshot_corpus("southsudan")),
        collector_path_for(get_snapshot_corpus("iran")),
        collector_path_for(get_snapshot_corpus("fiji")),
        collector_path_for(get_snapshot_corpus("dominican_republic")),
    ]
    helper = PACKAGE_HARVESTED_ROOT / "shared" / "common.py"
    assert helper.is_file()
    helper_text = helper.read_text(encoding="utf-8")
    assert "IPFS_DATASETS_LEGAL_CORPORA_ROOT" in helper_text
    assert "/workspace/legal-corpora" not in helper_text
    for path in later:
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert "/workspace/legal-corpora" not in text
        assert "/home/box/.cache/huggingface/token" not in text
    for entry in list_snapshot_corpora(include_aliases=False):
        path = collector_path_for(entry)
        assert path.is_file(), (entry.slug, entry.collector)
        text = path.read_text(encoding="utf-8")
        assert "/workspace/legal-corpora" not in text
        assert "/home/box/.cache/huggingface/token" not in text


def test_inspect_and_dry_run_do_not_hit_the_network():
    inspected = scrape_legal_data("germany", mode="inspect")
    dry_collect = scrape_legal_data("germany", mode="collect", dry_run=True)
    dry_snapshot = scrape_legal_data("DE", mode="snapshot", dry_run=True)

    assert inspected["status"] == "success"
    assert inspected["source"]["dataset_id"] == "endomorphosis/ipfs_germany_laws"
    assert dry_collect["status"] == "dry_run"
    assert dry_collect["collector"] == "collect_gii.py"
    assert dry_snapshot["status"] == "dry_run"
    assert dry_snapshot["not_legal_advice"] is True


def test_germany_jurisdiction_wrapper_satisfies_shared_interfaces(tmp_path):
    jurisdiction = get_jurisdiction("germany")

    assert jurisdiction.spec.country_code == "DE"
    assert jurisdiction.spec.hf_repo_ids["source"] == "endomorphosis/ipfs_germany_laws"
    assert isinstance(jurisdiction.discovery, DiscoveryProvider)
    assert isinstance(jurisdiction.fetcher, FetchProvider)
    assert isinstance(jurisdiction.parser, Parser)
    assert isinstance(jurisdiction.cid, CIDGenerator)

    coverage = jurisdiction.discovery.coverage_report(output_dir=tmp_path)
    assert coverage["jurisdiction"] == "DE"
    parsed = jurisdiction.parser.parse_document(
        {
            "id": "de-test",
            "title": "Testgesetz",
            "text": "§ 1 Scope",
            "documents": [{"id": "de-test-1", "article_number": "§ 1", "title": "Scope", "record_type": "article"}],
        }
    )
    assert parsed.fields["id"] == "de-test"
    assert parsed.articles[0].fields["article_number"] == "§ 1"
    generated = list(jurisdiction.cid.assign_record_cids([{"record_type": "law", "id": "de-test"}]))
    assert generated[0]["cid"].startswith("b")
    assert generated[0]["content_address"].startswith("ipfs://")


def test_load_instrument_records_reads_collection_record_v1(tmp_path):
    instruments = tmp_path / "de" / "instruments"
    instruments.mkdir(parents=True)
    (instruments / "de-test.json").write_text(
        json.dumps(
            {
                "id": "de-test",
                "title": "Testgesetz",
                "text": "Artikel 1",
                "law_status": "current",
                "documents": [{"id": "de-test-art-1", "article_number": "1", "text": "Artikel 1", "record_type": "article"}],
            }
        ),
        encoding="utf-8",
    )
    laws, articles = load_instrument_records("DE", output_dir=tmp_path)
    assert len(laws) == 1
    assert laws[0]["id"] == "de-test"
    assert len(articles) == 1
    assert articles[0]["law_id"] == "de-test"


def test_netherlands_native_registration_is_unchanged():
    jurisdiction = get_jurisdiction("netherlands")
    assert jurisdiction.spec.hf_repo_ids["base"] == "justicedao/ipfs_netherlands_laws"
    assert "wetten.overheid.nl law document pages" in jurisdiction.spec.official_sources


def test_sync_published_scrape_state_seeds_skip_keys_from_hub_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(tmp_path))
    rows = [
        {
            "id": "ao-1",
            "identifier": "1",
            "official_identifier": "1",
            "source_url": "http://moj.gov.ao/1.pdf",
        },
        {
            "id": "ao-constitution",
            "identifier": "Constituicao",
            "source_url": "http://moj.gov.ao/const.pdf",
        },
    ]
    state = sync_published_scrape_state(
        "angola",
        corpora_dir=tmp_path,
        rows=rows,
        revision="abc123",
        download=False,
    )
    assert state.law_count == 2
    assert state.skip_key_count >= 2
    assert state.error is None
    keys = load_skip_keys("AO", corpora_dir=tmp_path)
    assert "ao-1" in keys
    assert "http://moj.gov.ao/1.pdf" in keys
    assert "ao-constitution" in keys

    again = sync_published_scrape_state(
        "angola",
        corpora_dir=tmp_path,
        revision="abc123",
        download=True,
    )
    assert again.skipped_download is True
    assert again.law_count == 2

    from ipfs_datasets_py.processors.legal_scrapers.international.harvested.shared.common import existing_ids

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.international.harvested.shared.common.ROOT",
        tmp_path,
    )
    done = existing_ids("ao")
    assert "ao-1" in done
    assert "ao-constitution" in done


def test_collect_dry_run_reports_huggingface_skip_state(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(tmp_path))
    sync_published_scrape_state(
        "angola",
        corpora_dir=tmp_path,
        rows=[{"id": "ao-1", "identifier": "1", "source_url": "http://example.test/1.pdf"}],
        revision="rev1",
        download=False,
    )
    result = scrape_legal_data(
        "angola",
        mode="collect",
        output_dir=tmp_path,
        dry_run=True,
        parameters={"sync_huggingface": True},
    )
    assert result["status"] == "dry_run"
    hf_state = result["details"]["huggingface_scrape_state"]
    assert hf_state["dataset_id"] == "endomorphosis/ipfs_angola_laws"
    assert hf_state["skip_key_count"] >= 1
    assert hf_state["skipped_download"] is True


def test_skip_keys_include_slug_forms():
    keys = skip_keys_for_row("AO", {"id": "1", "identifier": "Diario 12", "source_url": "https://example.test/a.pdf"})
    assert "1" in keys
    assert "ao-1" in keys
    assert "https://example.test/a.pdf" in keys
