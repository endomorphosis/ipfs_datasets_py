"""Sorting the municipal seed by Wikidata population."""

from ipfs_datasets_py.processors.legal_scrapers.municipal.population import (
    apply_population,
    choose_population,
    sort_by_population,
    sort_municipalities_first,
)


def test_choose_population_keeps_the_largest_number() -> None:
    assert choose_population(["1000", "2500", "nope"]) == "2500"
    assert choose_population(["", "nope"]) == ""


def test_sort_puts_the_largest_population_first_and_blanks_last() -> None:
    rows = sort_by_population(
        [
            {"qid": "Q1", "name": "Small", "population": "10"},
            {"qid": "Q2", "name": "Big", "population": "900"},
            {"qid": "Q3", "name": "Zebra", "population": ""},
            {"qid": "Q4", "name": "Alpha", "population": ""},
        ]
    )
    assert [row["qid"] for row in rows] == ["Q2", "Q1", "Q4", "Q3"]


def test_largest_municipalities_come_before_larger_states() -> None:
    rows = sort_municipalities_first(
        [
            {"name": "North Rhine-Westphalia", "admin_level": "state", "population": "17932651"},
            {"name": "Berlin", "admin_level": "municipality", "population": "3677472"},
            {"name": "Small", "admin_level": "municipality", "population": "1000"},
            {"name": "No pop", "admin_level": "municipality", "population": ""},
        ]
    )
    assert [row["name"] for row in rows] == ["Berlin", "Small", "No pop", "North Rhine-Westphalia"]


def test_apply_population_does_not_replace_an_existing_value() -> None:
    kept = apply_population({"qid": "Q1", "population": "5"}, {"Q1": "99"})
    assert kept["population"] == "5"
    filled = apply_population({"qid": "Q2", "population": ""}, {"Q2": "42"})
    assert filled["population"] == "42"
