"""Homepage link extraction for municipal codes."""

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.municipal.code_links import (
    code_links_from_html,
    refresh_stored_links,
    vendor_for_host,
)


def test_german_satzung_link_is_kept_and_navigation_is_not() -> None:
    html = """
    <html><body>
      <a href="/rathaus">Rathaus</a>
      <a href="/politik/ortsrecht/hauptsatzung.pdf">Hauptsatzung</a>
      <a href="mailto:stadt@example.de">Mail</a>
    </body></html>
    """
    links = code_links_from_html(html, "https://www.example.de/", "DE")
    assert len(links) == 1
    assert links[0]["url"] == "https://www.example.de/politik/ortsrecht/hauptsatzung.pdf"
    assert links[0]["host"] == "example.de"
    assert links[0]["same_host"] == "true"


def test_italian_vendor_host_is_marked_external() -> None:
    html = '<a href="https://cloud.halley.it/albo/comune">Albo pretorio</a>'
    links = code_links_from_html(html, "https://www.comune.example.it/", "IT")
    assert links[0]["host"] == "cloud.halley.it"
    assert links[0]["same_host"] == "false"


def test_vendor_hosts_from_the_sample() -> None:
    assert vendor_for_host("halleyweb.com") == "halley"
    assert vendor_for_host("premolo.halleyegov.it") == "halley"
    assert vendor_for_host("cloud.halley.it") == "halley"
    assert vendor_for_host("coin.sedelectronica.es") == "sedelectronica"
    assert vendor_for_host("www.seu-e.cat") == "seu-e"
    assert vendor_for_host("webdelib.nicecotedazur.org") == "webdelib"
    assert vendor_for_host("cloud.urbi.it") == "urbi"
    assert vendor_for_host("asp.urbi.it") == "urbi"
    assert vendor_for_host("epaper.wittich.de") == "wittich"
    assert vendor_for_host("daten2.verwaltungsportal.de") == "verwaltungsportal"
    assert vendor_for_host("albotelematico.tn.it") == "albotelematico"
    assert vendor_for_host("dgegovpa.it") == "dgegovpa"
    assert vendor_for_host("albo.tinnvision.cloud") == "tinnvision"
    assert vendor_for_host("trasparenza.parsec326.it") == "parsec"
    assert vendor_for_host("leipzig.de") == ""


def test_accented_french_keyword_matches() -> None:
    html = '<a href="/mairie/arretes">Arrêtés municipaux</a>'
    links = code_links_from_html(html, "https://ville.example.fr/accueil", "FR")
    assert links[0]["url"] == "https://ville.example.fr/mairie/arretes"


def test_french_climate_and_sector_rules_are_not_code_links() -> None:
    html = """
    <a href="/climat">Stratégie d’adaptation au dérèglement climatique</a>
    <a href="/plages">Réglementation des plages</a>
    <a href="/actes">Actes réglementaires</a>
    """
    links = code_links_from_html(html, "https://ville.example.fr/", "FR")
    assert [link["url"] for link in links] == ["https://ville.example.fr/actes"]


def test_refresh_relabels_vendors_and_drops_loose_french_links(tmp_path: Path) -> None:
    path = tmp_path / "IT.jsonl"
    path.write_text(
        json.dumps(
            {
                "qid": "Q1",
                "country_code": "IT",
                "code_links": [
                    {
                        "url": "https://cloud.urbi.it/albo",
                        "text": "Albo pretorio",
                        "host": "cloud.urbi.it",
                        "same_host": "false",
                        "vendor": "",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    french = tmp_path / "FR.jsonl"
    french.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "qid": "Q2",
                        "country_code": "FR",
                        "code_links": [
                            {
                                "url": "https://ville.example.fr/climat",
                                "text": "dérèglement climatique",
                                "host": "ville.example.fr",
                                "same_host": "true",
                                "vendor": "",
                            },
                            {
                                "url": "https://ville.example.fr/actes",
                                "text": "Actes administratifs",
                                "host": "ville.example.fr",
                                "same_host": "true",
                                "vendor": "",
                            },
                        ],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    italy = refresh_stored_links(path)
    assert italy["links_before"] == italy["links_after"] == 1
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["code_links"][0]["vendor"] == "urbi"
    france = refresh_stored_links(french)
    assert france["links_before"] == 2
    assert france["links_after"] == 1
    kept = json.loads(french.read_text(encoding="utf-8"))
    assert kept["code_links"][0]["text"] == "Actes administratifs"
