from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_scraper_module():
    root = Path(__file__).resolve().parents[3]
    path = root / "ipfs_datasets_py" / "processors" / "legal_scrapers" / "netherlands_laws_scraper.py"
    spec = importlib.util.spec_from_file_location("netherlands_laws_scraper_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


scraper = _load_scraper_module()


SRU_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://docs.oasis-open.org/ns/search-ws/sruResponse"
    xmlns:dcterms="http://purl.org/dc/terms/">
  <version>2.0</version>
  <numberOfRecords>250</numberOfRecords>
  <records>
    <record>
      <recordData>
        <gzd>
          <originalData>
            <meta>
              <dcterms:identifier>BWBR0001854</dcterms:identifier>
              <dcterms:title>Wetboek van Strafrecht</dcterms:title>
            </meta>
          </originalData>
        </gzd>
      </recordData>
      <recordPosition>1</recordPosition>
    </record>
    <record>
      <recordData>
        <gzd>
          <originalData>
            <meta>
              <dcterms:identifier>BWBR0001854</dcterms:identifier>
            </meta>
          </originalData>
        </gzd>
      </recordData>
      <recordPosition>2</recordPosition>
    </record>
    <record>
      <recordData>
        <gzd>
          <originalData>
            <meta>
              <dcterms:identifier>BWBR0002656</dcterms:identifier>
            </meta>
          </originalData>
        </gzd>
      </recordData>
      <recordPosition>3</recordPosition>
    </record>
  </records>
  <nextRecordPosition>101</nextRecordPosition>
</searchRetrieveResponse>
"""


def test_sru_seed_url_is_official_supported_discovery_source():
    seed = scraper._build_sru_seed_url("dcterms.type==wet")

    assert scraper._is_supported_seed_url(seed)
    assert scraper._is_sru_bwb_seed_url(seed)
    assert not scraper._is_supported_seed_url("https://wetten-overheid.nl/wetgeving/bladeren")


def test_extract_sru_document_links_dedupes_and_paginates():
    seed = scraper._build_sru_seed_url("dcterms.type==wet", start_record=1, maximum_records=100)

    links, next_url, metadata = scraper._extract_sru_document_links(SRU_FIXTURE, seed)

    assert links == [
        "https://wetten.overheid.nl/BWBR0001854/",
        "https://wetten.overheid.nl/BWBR0002656/",
    ]
    assert "startRecord=101" in next_url
    assert metadata["number_of_records"] == 250
    assert metadata["next_record_position"] == 101
    assert metadata["record_positions_seen"] == 3
    assert metadata["identifiers_seen"] == 3


def test_html_document_link_normalization_dedupes_trailing_slash_variants():
    html = """
    <html><body>
      <a href="/BWBR0001854">without slash</a>
      <a href="/BWBR0001854/">with slash</a>
      <a href="https://example.com/BWBR9999999/">third party</a>
    </body></html>
    """

    assert scraper._extract_document_links(html, "https://wetten.overheid.nl/zoeken") == [
        "https://wetten.overheid.nl/BWBR0001854/"
    ]
