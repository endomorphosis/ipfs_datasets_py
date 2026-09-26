"""Official-website extraction from Wikipedia infoboxes."""

from ipfs_datasets_py.processors.legal_scrapers.municipal.websites import (
    clean_website,
    official_website_from_wikitext,
)


def test_search_result_must_match_the_place_or_a_government_domain() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.municipal.websites import result_matches_place

    assert result_matches_place("http://huila.gov.ao/", "Huíla Province")
    assert result_matches_place("https://www.oromia.gov.et/", "Oromia Region")
    assert result_matches_place("https://kanostate.gov.ng/", "Kano State")
    assert not result_matches_place("https://www.auvergnerhonealpes.fr/", "Auvergne-Rhône-Alpes")
    assert not result_matches_place("https://advocacy4oromia.org/articles/oromia", "Oromia Region")
    assert not result_matches_place("https://ethiopia.iom.int/oromia-region", "Oromia Region")
    assert not result_matches_place("https://www.peru.travel/destinations/lima", "Lima")
    assert not result_matches_place("https://e.gov.ph/", "")
    assert not result_matches_place("https://en.wikipedia.org/wiki/Huila", "Huíla Province")
    assert not result_matches_place("https://www.tripadvisor.com/Huila", "Huíla Province")


def test_infobox_website_is_kept_and_archives_are_not() -> None:
    text = """
    {{Infobox settlement
    | name = Montevideo
    | website = http://www.montevideo.gub.uy/
    }}
    """
    assert official_website_from_wikitext(text) == "http://www.montevideo.gub.uy/"
    assert clean_website("https://web.archive.org/web/1/http://example.gub.uy") == ""
    assert official_website_from_wikitext("| website = {{URL|https://en.wikipedia.org/wiki/X}}") == ""
