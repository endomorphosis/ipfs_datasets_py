"""Law, metadata, and website labels. Sampling does not admit a heading token."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
    _instrument_record_type,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    split_structured_units,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    expand_legal_record,
    render_atomic,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_world_v11_row import (
    project_world_v11_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.sample_structure import (
    sample_parquet,
    sample_records,
)

_SHA = "a" * 40
_EXAM = (
    "Reife- und Diplomprüfung sowie Diplomprüfung in der Bildungsanstalt "
    "für Kindergartenpädagogik"
)


def _world(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "cid": "bafy-world",
        "country_code": "DE",
        "doc_type": "statute",
        "title_native": "Gesetz",
        "number": "1",
        "text": "Les lois",
        "content_complete": True,
        "source_policy": None,
        "source_official": True,
        "source_url": "https://example.test/laws/1",
        "language": "de",
    }
    row.update(overrides)
    return row


def test_title_shell_is_metadata_and_keeps_its_text() -> None:
    record = project_world_v11_row(
        _world(title_native=_EXAM, text=_EXAM, number=None),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert record is not None
    assert record["text"] == _EXAM
    assert record["provenance"]["document_role"] == "metadata"
    assert record["provenance"]["document_role_reason"] == "title_shell"
    atoms = expand_legal_record(record)
    assert len(atoms) == 1
    assert atoms[0]["text"] == _EXAM
    document = render_atomic(atoms[0], "jsonld")
    assert document["@type"] == "DigitalDocument"
    assert document["@context"] == "https://schema.org"
    assert document["text"] == _EXAM
    properties = {
        item["propertyID"]: item["value"] for item in document["additionalProperty"]
    }
    assert properties["document_role"] == "metadata"


def test_site_chrome_is_informative_and_a_statute_on_that_host_stays_a_law() -> None:
    page = project_world_v11_row(
        _world(
            doc_type="website",
            title_native="Search",
            text="Home\nSearch\nContact us\nThis website uses cookies\n",
            source_url="https://example.test/search",
        ),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert page is not None
    assert page["provenance"]["document_role"] == "informative"
    assert str(page["text"]).startswith("Home")
    cleaned = expand_legal_record(page)
    assert len(cleaned) == 1
    assert cleaned[0]["provenance"]["document_role"] == "informative"
    informative = render_atomic(cleaned[0], "jsonld")
    assert informative["@type"] == "WebPage"
    assert informative["text"]
    assert "Article" not in str(informative["text"])

    act = (
        "Article 1 This Act applies to the processing of personal data.\n"
        "Article 2 The controller shall publish a notice on the website.\n"
    )
    statute = project_world_v11_row(
        _world(
            title_native="Data Protection Act",
            text=act,
            source_url="https://example.test/privacy-policy",
            language="en",
        ),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert statute is not None
    assert statute["provenance"]["document_role"] == "law"
    atoms = expand_legal_record(statute)
    assert len(atoms) == 2
    assert atoms[0]["provenance"]["article"] == "1"
    assert atoms[1]["provenance"]["section"] == "2"
    document = render_atomic(atoms[0], "jsonld")
    assert document["@type"] == "Legislation"
    assert document["text"].startswith("Article 1")
    plain = render_atomic(atoms[0], "text")
    assert plain["document_role"] == "law"
    assert plain["text"].startswith("Article 1")
    assert "document_role" not in plain["text"]


def test_short_operative_text_and_a_gazette_sentence_stay_laws() -> None:
    short = expand_legal_record(
        {"entry_cid": "keep", "title": "Code civil", "text": "Les lois", "provenance": {}}
    )
    assert len(short) == 1
    assert short[0]["text"] == "Les lois"
    assert short[0]["provenance"]["document_role"] == "law"
    gazette = expand_legal_record(
        {
            "entry_cid": "gaz",
            "title": "Appointments",
            "text": "The Clerk shall publish notice of each appointment in the Gazette.",
            "provenance": {},
        }
    )
    assert gazette[0]["provenance"]["document_role"] == "law"
    assert "Gazette" in gazette[0]["text"]


def test_numbered_captions_stay_one_law_and_are_reported_as_candidates() -> None:
    text = (
        "1. Kurzbezeichnung\n"
        "Dieses Gesetz heißt Beispielgesetz.\n"
        "2. Anwendungsbereich\n"
        "Dieses Gesetz gilt im ganzen Bundesgebiet.\n"
    )
    assert split_structured_units(text, language="de") == []
    atoms = expand_legal_record(
        {
            "entry_cid": "de",
            "title": "Beispielgesetz",
            "text": text,
            "language": "de",
            "provenance": {},
        }
    )
    assert len(atoms) == 1
    assert "Kurzbezeichnung" in atoms[0]["text"]
    assert "216 East" not in atoms[0]["text"]
    report = sample_records(
        [
            {
                "title": "Beispielgesetz",
                "text": text,
                "language": "de",
                "provenance": {},
            },
            {
                "title": _EXAM,
                "text": _EXAM,
                "language": "de",
                "provenance": {},
            },
            {
                "title": "Search",
                "text": "Home\nSearch\nContact us\n",
                "source_url": "https://example.test/search",
                "provenance": {},
            },
        ]
    )
    assert report["rows"] == 3
    assert report["roles"] == {"law": 1, "metadata": 1, "informative": 1}
    assert report["empty_after_clean"] == 0
    assert report["law_atoms"] == 1
    lines = {item["line"] for item in report["heading_candidates"]}
    assert "1. Kurzbezeichnung" in lines
    assert "2. Anwendungsbereich" in lines
    assert all(item["kind"] == "numbered_caption" for item in report["heading_candidates"])


def test_article_locators_are_counted_and_a_large_shard_is_refused(tmp_path) -> None:
    act = (
        "Title 1 General provisions\n"
        "Chapter 2 Scope\n"
        "Article 1 Alpha provision applies.\n"
        "Article 2 Beta provision applies.\n"
    )
    report = sample_records(
        [{"title": "Code", "text": act, "language": "en", "citation": "Code civil", "provenance": {}}]
    )
    assert report["roles"]["law"] == 1
    assert report["locator_atoms"]["title"] >= 1
    assert report["locator_atoms"]["chapter"] >= 1
    assert report["locator_atoms"]["article"] >= 1
    assert report["locator_atoms"]["section"] >= 1
    assert report["heading_candidates"] == []

    shard = tmp_path / "part.parquet"
    pq.write_table(
        pa.table(
            {
                "body": [act],
                "title": ["Code"],
                "language": ["en"],
            }
        ),
        shard,
    )
    sampled = sample_parquet(shard, limit=60)
    assert sampled["rows"] == 1
    assert sampled["locator_atoms"]["article"] >= 1
    huge = tmp_path / "huge.parquet"
    huge.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    try:
        sample_parquet(huge)
    except ValueError as exc:
        assert "8 MiB" in str(exc)
    else:
        raise AssertionError("expected the large shard to be refused")


def test_catalog_doc_type_stays_metadata_after_instrument_type_coercion() -> None:
    record = project_world_v11_row(
        _world(
            doc_type="catalog",
            title_native="Title index",
            text="List of titles in this code.",
        ),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert record is not None
    assert record["instrument_type"] == "statute"
    assert record["provenance"]["document_role"] == "metadata"
    assert record["provenance"]["document_role_reason"] == "catalog_type"
    assert record["text"] == "List of titles in this code."


def test_country_normalizer_keeps_a_law_and_marks_a_site_page_as_notice() -> None:
    assert (
        _instrument_record_type(
            {"document_type": "statute", "record_type": "law"},
            "Article 6 Loi relative aux routes publiques",
            text="The court shall apply this Act throughout the territory and bind every person.",
            source_url="https://example.test/art6",
            language="en",
        )
        == "law"
    )
    assert (
        _instrument_record_type(
            {"document_type": "newsletter", "record_type": "newsletter"},
            "Newsletter mbi ceshtjet europiane",
            text="This newsletter tells readers what the assembly discussed this week.",
        )
        == "notice"
    )
    assert (
        _instrument_record_type(
            {},
            "Council website",
            text="Home\nSearch\nSitemap\nContact us\n",
            source_url="https://example.test/search",
            language="en",
        )
        == "notice"
    )
    assert (
        _instrument_record_type(
            {},
            _EXAM,
            text=_EXAM,
            language="de",
        )
        == "notice"
    )
