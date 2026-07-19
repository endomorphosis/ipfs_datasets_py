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


def test_legal_ir_projection_extracts_transfer_codification_lineage() -> None:
    predicates = _projection_predicates(
        "42 U.S.C. 2751.: \u00a72751. Transferred Editorial Notes Codification "
        "Section 2751, originally enacted as section 121 of Pub. L. 88-452, "
        "was renumbered section 441 of Pub. L. 89-329 and transferred to "
        "section 1087-51 of Title 20, Education."
    )

    assert predicates["status_keyword"] == ["transferred"]
    assert predicates["status_transfer_destination_citation"] == [
        "20 U.S.C. 1087-51"
    ]
    assert predicates["status_codification_origin_section"] == ["121"]
    assert predicates["status_codification_origin_public_law"] == ["88-452"]
    assert predicates["status_codification_renumbered_section"] == ["441"]
    assert predicates["status_codification_renumbered_public_law"] == ["89-329"]


def test_legal_ir_projection_promotes_sparse_graph_guidance_to_view_alignment() -> None:
    triples = augment_legal_ir_projection_triples(
        [
            {
                "subject": "us-code-10-2515",
                "predicate": "action",
                "object": "repair_multiview_legal_ir_graph_projection",
            },
            {
                "subject": "us-code-10-2515",
                "predicate": "predicted_view",
                "object": "knowledge_graphs_neo4j_compat",
            },
            {
                "subject": "us-code-10-2515",
                "predicate": "target_component",
                "object": "neo4j_compat",
            },
        ]
    )
    values = {
        (triple["predicate"], triple["object"])
        for triple in triples
        if triple["predicate"].startswith("learned_legal_ir_")
    }

    assert (
        "learned_legal_ir_predicted_view",
        "knowledge_graphs.neo4j_compat",
    ) in values
    assert (
        "learned_legal_ir_target_view",
        "knowledge_graphs.neo4j_compat",
    ) in values
    assert (
        "learned_legal_ir_view_gap",
        "knowledge_graphs.neo4j_compat:0.000000",
    ) in values


def test_legal_ir_projection_graph_repair_action_adds_neo4j_target_view() -> None:
    triples = augment_legal_ir_projection_triples(
        [
            {
                "subject": "us-code-22-290k-5",
                "predicate": "compiler_guidance_action",
                "object": "repair_multiview_legal_ir_graph_projection",
            },
        ]
    )
    values = {
        (triple["predicate"], triple["object"])
        for triple in triples
        if triple["predicate"].startswith("learned_legal_ir_")
    }

    assert (
        "learned_legal_ir_target_view",
        "knowledge_graphs.neo4j_compat",
    ) in values
    assert (
        "learned_legal_ir_view_gap",
        "knowledge_graphs.neo4j_compat:1.000000",
    ) in values


def test_legal_ir_projection_promotes_family_gap_guidance_to_neo4j_view() -> None:
    triples = augment_legal_ir_projection_triples(
        [
            {
                "subject": "compiler-guidance-family-gap",
                "predicate": "compiler_guidance_attribution",
                "object": (
                    '{"legal_ir_view_family_gaps": '
                    '{"knowledge_graph:underrepresented": {"count": 2}}}'
                ),
            },
        ]
    )
    values = {
        (triple["predicate"], triple["object"])
        for triple in triples
        if triple["predicate"].startswith("learned_legal_ir_")
    }

    assert (
        "learned_legal_ir_target_view",
        "knowledge_graphs.neo4j_compat",
    ) in values
    assert (
        "learned_legal_ir_view_gap",
        "knowledge_graphs.neo4j_compat:2.000000",
    ) in values


def test_legal_ir_projection_structural_us_code_facts_add_neo4j_target_view() -> None:
    samples = [
        (
            "us-code-10-2515-cb1304b3980adf2a",
            "10 U.S.C. 2515: U.S.C. Title 10 - ARMED FORCES 10 U.S.C. "
            "United States Code, 2024 Edition Title 10 - ARMED FORCES "
            "Subtitle A - General Military Law PART IV - SERVICE, SUPPLY, "
            "AND PROPERTY CHAPTER 148 - REPEALED SUBCHAPTER III - REPEALED "
            "Sec. 2515 - Repealed.",
        ),
        (
            "us-code-22-290k-5-2914184e2690e597",
            "22 U.S.C. 290k-5: U.S.C. Title 22 - FOREIGN RELATIONS AND "
            "INTERCOURSE 22 U.S.C. United States Code, 2024 Edition Title "
            "22 - FOREIGN RELATIONS AND INTERCOURSE CHAPTER 7 - "
            "INTERNATIONAL BUREAUS, CONGRESSES, ETC. SUBCHAPTER XXVI - "
            "MULTILATERAL INVESTMENT GUARANTEE AGENCY Sec. 290k-5 - "
            "Repealed.",
        ),
    ]

    for subject, text in samples:
        triples = augment_legal_ir_projection_triples(
            [{"subject": subject, "predicate": "sample_text", "object": text}]
        )
        values = {
            (triple["predicate"], triple["object"])
            for triple in triples
        }

        assert ("usc_hierarchy_projection", "true") in values
        assert ("status_keyword", "repealed") in values
        assert (
            "learned_legal_ir_predicted_view",
            "knowledge_graphs.neo4j_compat",
        ) in values
        assert (
            "learned_legal_ir_target_view",
            "knowledge_graphs.neo4j_compat",
        ) in values
        assert (
            "learned_legal_ir_view_gap",
            "knowledge_graphs.neo4j_compat:0.000000",
        ) in values
