"""World municipal seed shaping, without Wikidata."""

from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
    _dedupe_rows,
    _prefer_iso,
    output_path,
    rows_from_bindings,
    skip_class_label,
)


def test_catalog_keeps_one_row_and_marks_done_classes() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
        FIRST_LEVEL,
        assemble_catalog,
    )

    records = assemble_catalog(
        [
            {
                "qid": "Q1",
                "label": "municipality of Sweden",
                "role": "municipality",
                "depth": 1,
                "root": "Q15284",
            },
            {
                "qid": "Q1",
                "label": "municipality of Sweden",
                "role": "municipality",
                "depth": 2,
                "root": "Q15284",
            },
            {
                "qid": "Q2",
                "label": "state of India",
                "role": "municipality",
                "depth": 0,
                "root": "gap",
            },
            {
                "qid": "Q3",
                "label": "former municipality of Sweden",
                "role": "municipality",
                "depth": 1,
                "root": "Q15284",
            },
            {
                "qid": "Q4",
                "label": "Bicycle friendly municipality in Bavaria",
                "role": "municipality",
                "depth": 3,
                "root": "Q15284",
            },
            {
                "qid": "Q5",
                "label": "Q5",
                "role": "municipality",
                "depth": 3,
                "root": "Q15284",
            },
            {
                "qid": "Q485258",
                "label": "federative unit of Brazil",
                "role": "adm1",
                "depth": 0,
                "root": FIRST_LEVEL,
            },
        ],
        done=["Q1"],
    )
    by_qid = {row["qid"]: row for row in records}
    assert "Q3" not in by_qid
    assert "Q4" not in by_qid
    assert "Q5" not in by_qid
    assert by_qid["Q1"]["done"] is True
    assert by_qid["Q1"]["role"] == "municipality"
    assert by_qid["Q1"]["depth"] == 1
    assert by_qid["Q2"]["role"] == "adm1"
    assert by_qid["Q2"]["admin_level"] == "state"
    assert by_qid["Q2"]["done"] is False
    assert by_qid["Q485258"]["admin_level"] == "state"


def test_gap_classes_are_local_governments() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
        GAP_CLASSES,
        skip_class_label,
    )

    labels = {label for _, label in GAP_CLASSES}
    assert "municipality of Switzerland" in labels
    assert "territorial authority of New Zealand" in labels
    assert "local government area of Australia" in labels
    assert "province of Peru" not in labels
    assert "region of Ghana" not in labels
    assert all(not skip_class_label(label) for _, label in GAP_CLASSES)
    assert len({qid for qid, _ in GAP_CLASSES}) == len(GAP_CLASSES)


def test_state_and_province_classes_are_not_municipalities() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (
        admin_level_for_label,
        is_province_class,
    )

    assert is_province_class("state of India")
    assert is_province_class("province of Laos")
    assert is_province_class("governorate of Yemen")
    assert admin_level_for_label("state of India") == "state"
    assert admin_level_for_label("states and union territories of India") == "state"
    assert admin_level_for_label("province of Laos") == "province"
    assert admin_level_for_label("insular area of the United States") == "adm1"
    assert admin_level_for_label("U.S. state") == "state"
    assert admin_level_for_label("federative unit of Brazil") == "state"
    assert not is_province_class("municipality of Sweden")
    assert not is_province_class("town panchayat")
    assert not is_province_class("vilayet of Tajik ASSR")
    assert not is_province_class("state in the Holy Roman Empire")
    bindings = [
        {
            "item": {"value": "http://www.wikidata.org/entity/Q2"},
            "iso": {"value": "IN"},
            "en": {"value": "Kerala"},
        }
    ]
    rows = rows_from_bindings(bindings, "Q131541", admin_level="state")
    assert rows[0]["admin_level"] == "state"
    assert rows[0]["country_code"] == "IN"


def test_skip_historical_municipality_classes() -> None:
    assert skip_class_label("former municipality of Sweden")
    assert skip_class_label("abolished municipality in Italy")
    assert skip_class_label("theoretical municipality")
    assert not skip_class_label("municipality of Sweden")
    assert not skip_class_label("market municipality")


def test_prefer_known_country_over_eu() -> None:
    assert _prefer_iso(["EU", "FR"]) == "FR"
    assert _prefer_iso(["EU"]) == ""


def test_bindings_collapse_multiple_websites() -> None:
    bindings = [
        {
            "item": {"value": "http://www.wikidata.org/entity/Q1"},
            "iso": {"value": "SE"},
            "en": {"value": "Stockholm"},
            "site": {"value": "https://start.stockholm"},
        },
        {
            "item": {"value": "http://www.wikidata.org/entity/Q1"},
            "iso": {"value": "SE"},
            "en": {"value": "Stockholm"},
            "site": {"value": "https://stockholm.se"},
        },
    ]
    rows = rows_from_bindings(bindings, "Q127448")
    assert len(rows) == 1
    assert rows[0]["country_code"] == "SE"
    assert rows[0]["region"] == "europe"
    assert rows[0]["source_urls"] == ["https://start.stockholm", "https://stockholm.se"]
    assert rows[0]["status"] == "not_scraped"


def test_dedupe_keeps_the_row_that_has_a_website() -> None:
    rows = _dedupe_rows(
        [
            {"qid": "Q1", "name": "", "source_urls": []},
            {"qid": "Q1", "name": "Oslo", "source_urls": ["https://oslo.kommune.no"]},
        ]
    )
    assert rows == [{"qid": "Q1", "name": "Oslo", "source_urls": ["https://oslo.kommune.no"]}]


def test_curated_us_file_is_not_the_wikidata_output(tmp_path) -> None:
    assert output_path(tmp_path, "US", "americas") == tmp_path / "americas" / "US_wikidata.jsonl"
    assert output_path(tmp_path, "NL", "europe") == tmp_path / "europe" / "NL.jsonl"
    assert output_path(tmp_path, "SE", "europe") == tmp_path / "europe" / "SE.jsonl"
