"""Router decisions for the class walk stay inside the prompt."""

from ipfs_datasets_py.processors.legal_scrapers.municipal.traverse import (
    apply_router,
    audit_targets,
    decision_from_label,
    parse_router_reply,
    select_audit_classes,
    split_pending,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import level_from_label


def test_coverage_rows_stay_in_the_requested_country() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.municipal.traverse import rows_from_coverage_bindings

    rows = rows_from_coverage_bindings(
        [
            {
                "item": {"value": "http://www.wikidata.org/entity/Q10"},
                "en": {"value": "Central and Western"},
                "class": {"value": "http://www.wikidata.org/entity/Q50256"},
                "classLabel": {"value": "districts of Hong Kong"},
                "site": {"value": "https://www.districtcouncils.gov.hk/"},
                "pop": {"value": "243266"},
                "gnis": {"value": ""},
            },
            {
                "item": {"value": "http://www.wikidata.org/entity/Q11"},
                "en": {"value": "Best Editing"},
                "class": {"value": "http://www.wikidata.org/entity/Q1"},
                "classLabel": {"value": "film award"},
            },
        ],
        "HK",
    )
    assert [row["qid"] for row in rows] == ["Q10"]
    assert rows[0]["country_code"] == "HK"
    assert rows[0]["admin_level"] == "district"
    assert rows[0]["population"] == "243266"
    assert rows[0]["qid"] == "Q10"
    assert rows[0]["source_urls"] == ["https://www.districtcouncils.gov.hk/"]


def test_audit_keeps_a_new_district_and_skips_a_done_class() -> None:
    assert audit_targets({"SG": 0, "FR": 100, "IE": 4}, ["SG", "FR", "IE", "EU"]) == ["SG", "IE"]
    chosen = select_audit_classes(
        [
            {"qid": "Q1", "label": "district of Hong Kong", "n": 18},
            {"qid": "Q2", "label": "district of Hong Kong", "n": 18},
            {"qid": "Q3", "label": "census area of Alaska", "n": 11},
            {"qid": "Q4", "label": "human", "n": 5},
            {"qid": "Q5", "label": "village of Japan", "n": 5000},
            {"qid": "Q6", "label": "town", "n": 12},
        ],
        done=["Q1"],
    )
    assert [row["qid"] for row in chosen] == ["Q2"]
    assert chosen[0]["admin_level"] == "district"


def test_district_and_parish_are_their_own_levels() -> None:
    assert level_from_label("district of Cyprus") == "district"
    assert level_from_label("parish of Barbados") == "parish"
    assert level_from_label("union territory of India") == "territory"
    assert level_from_label("city of California") is None
    assert level_from_label("insular area of the United States") is None


def test_router_reply_drops_unknown_qids() -> None:
    rows = [{"qid": "Q1", "label": "city of California"}, {"qid": "Q2", "label": "theme"}]
    reply = """```json
    [
      {"qid": "Q1", "action": "keep", "level": "municipality"},
      {"qid": "Q9", "action": "keep", "level": "municipality"},
      {"qid": "Q2", "action": "drop", "level": "province"}
    ]
    ```"""
    decided = parse_router_reply(rows, reply)
    assert decided["Q1"] == {"keep": True, "level": "municipality"}
    assert decided["Q2"]["keep"] is False
    assert "Q9" not in decided


def test_router_line_and_embedded_json_are_accepted() -> None:
    rows = [{"qid": "Q1", "label": "atoll of the Maldives"}]
    assert parse_router_reply(rows, "Sure.\nQ1 keep territory\n")["Q1"]["level"] == "territory"
    embedded = parse_router_reply(rows, 'Here you go: [{"qid": "Q1", "action": "keep", "level": "territory"}]')
    assert embedded["Q1"]["keep"] is True


def test_split_sends_only_ambiguous_labels_to_the_router() -> None:
    clear, ambiguous = split_pending(
        [
            {"qid": "Q1", "label": "district of Samoa"},
            {"qid": "Q2", "label": "city of Texas"},
            {"qid": "Q3", "label": "list of towns in Nova Scotia"},
            {"qid": "Q4", "label": "ashkharh"},
            {"qid": "Q5", "label": "widgetship"},
        ]
    )
    by_qid = {row["qid"]: row for row in clear}
    assert by_qid["Q1"]["admin_level"] == "district"
    assert by_qid["Q2"]["admin_level"] == "municipality"
    assert by_qid["Q3"]["keep"] is False
    assert by_qid["Q4"]["keep"] is False
    assert decision_from_label("atoll of the Maldives") == {"keep": True, "level": "territory"}
    assert [row["qid"] for row in ambiguous] == ["Q5"]
    kept, pending = apply_router(
        ambiguous,
        lambda _prompt: 'note [{"qid": "Q5", "action": "keep", "level": "territory"}, {"qid": "Q99", "action": "keep", "level": "state"}]',
    )
    assert kept[0]["admin_level"] == "territory"
    assert "Q99" not in {row["qid"] for row in kept}
    assert pending == []
