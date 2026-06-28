from ipfs_datasets_py.knowledge_graphs.neo4j_compat.legal_ir_projection import (
    augment_legal_ir_projection_triples,
)


def _projection_predicates(text: str) -> dict[str, list[str]]:
    triples = augment_legal_ir_projection_triples(
        [{"subject": "doc", "predicate": "sample_text", "object": text}]
    )
    by_predicate: dict[str, list[str]] = {}
    for triple in triples:
        by_predicate.setdefault(triple["predicate"], []).append(triple["object"])
    return by_predicate


def test_legal_ir_projection_marks_primary_repealed_section_status() -> None:
    predicates = _projection_predicates(
        "42 U.S.C. 1411d. \u00a71411d. Repealed. Pub. L. 93-383, title II, "
        "\u00a7204, Aug. 22, 1974, 88 Stat. 668 Section, act Aug. 2, 1954, "
        "ch. 649, title VIII, \u00a7815, 68 Stat. 647, required submission "
        "of specifications."
    )

    assert predicates["status_keyword"] == ["repealed"]
    assert predicates["status_keyword_repealed"] == ["true"]
    assert predicates["status_scope"] == ["section_heading"]
    assert predicates["section_catchline"] == ["Repealed"]


def test_legal_ir_projection_keeps_editorial_note_status_out_of_primary_status() -> None:
    predicates = _projection_predicates(
        "12 U.S.C. 211 U.S.C. Title 12 - BANKS AND BANKING CHAPTER 2 - "
        "NATIONAL BANKS SUBCHAPTER XIV - BANK CONSERVATION ACT Sec. 211 - "
        "Rules and regulations From the U.S. Government Publishing Office, "
        "www.gpo.gov \u00a7211. Rules and regulations (a) In general The "
        "Comptroller of the Currency may prescribe such rules and regulations "
        "as the Comptroller may deem necessary to carry out the provisions of "
        "this Act. Editorial Notes References in Text Section 51d of this "
        "title was repealed by act June 30, 1947, ch. 166, title II, "
        "\u00a7206(b), (o), 61 Stat. 208. Amendments 1989 -Pub. L. 101-73 "
        "amended section generally."
    )

    assert "status_keyword" not in predicates
    assert "status_keyword_repealed" not in predicates
    assert predicates["editorial_reference_status_keyword"] == ["repealed"]
    assert predicates["editorial_reference_status_keyword_repealed"] == ["true"]
    assert predicates["section_catchline"] == ["Rules and regulations"]


def test_legal_ir_projection_keeps_prior_provision_transfer_out_of_primary_status() -> None:
    predicates = _projection_predicates(
        "42 U.S.C. 6979b. \u00a76979b. Law enforcement authority The Attorney "
        "General of the United States shall, at the request of the "
        "Administrator and on the basis of a showing of need, deputize "
        "qualified employees. Editorial Notes Prior Provisions A prior section "
        "7010 of Pub. L. 89-272, which was classified to section 6979a of this "
        "title, was renumbered section 3020 and transferred to section 6939b "
        "of this title."
    )

    assert "status_keyword" not in predicates
    assert "status_keyword_transferred" not in predicates
    assert predicates["editorial_reference_status_keyword"] == ["transferred"]
    assert predicates["editorial_reference_status_keyword_transferred"] == ["true"]
    assert predicates["section_catchline"] == ["Law enforcement authority"]
