from ipfs_datasets_py.processors.legal_data import (
    build_pleading_caption,
    build_document_knowledge_graph,
    paginate_pleading_lines,
    parse_legal_document,
    parse_legal_document_to_graph,
    render_pleading_caption_block,
    summarize_formal_document,
    validate_formal_document,
)


SAMPLE_DOCUMENT = """IN THE SUPERIOR COURT OF EXAMPLE COUNTY
STATE OF EXAMPLE

Case No. 24-CV-1001

JANE DOE, Plaintiff,
v.
ACME CORP., Defendant.

MOTION TO COMPEL

I. FACTS
1. Plaintiff served discovery.
2. Defendant refused production.

## Relief Requested
- Compel production
- Award fees
"""


def test_parse_legal_document_extracts_header_and_sections():
    parsed = parse_legal_document(SAMPLE_DOCUMENT)

    assert parsed.header is not None
    assert parsed.header.case_number == "Case No. 24-CV-1001"
    assert parsed.numbered_paragraph_count == 2
    assert parsed.bullet_count == 2
    assert parsed.all_caps_heading_count >= 1
    assert parsed.title == "MOTION TO COMPEL"


def test_build_document_knowledge_graph_creates_document_nodes_and_edges():
    parsed = parse_legal_document(SAMPLE_DOCUMENT)
    graph = build_document_knowledge_graph(parsed, graph_id="complaint")

    node_types = {node["type"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}

    assert "document" in node_types
    assert "court_line" in node_types
    assert "party_line" in node_types
    assert "header_title" in node_types or "roman_heading" in node_types
    assert "filed_in" in edge_types
    assert "has_section" in edge_types


def test_parse_legal_document_to_graph_returns_combined_payload():
    payload = parse_legal_document_to_graph(SAMPLE_DOCUMENT, graph_id="combined")

    assert payload["summary"]["section_count"] >= 2
    assert payload["knowledge_graph"]["graph_id"] == "combined"
    assert payload["parsed_document"]["title"] == "MOTION TO COMPEL"


def test_caption_rendering_and_pagination_helpers_work():
    caption = build_pleading_caption(
        court_lines=["IN THE UNITED STATES DISTRICT COURT", "FOR THE DISTRICT OF EXAMPLE"],
        case_number="Civil Action No. 1:24-cv-1001",
        party_lines=["JANE DOE, Plaintiff,", "v.", "ACME CORP., Defendant."],
        filing_title_lines=["COMPLAINT FOR BREACH OF CONTRACT"],
        left_title="Civil Action",
        right_title="Case No.",
    )

    rendered = render_pleading_caption_block(caption)
    pages = paginate_pleading_lines(["1. Fact one.", "2. Fact two.", "3. Fact three."], page_size=2, footer_label="Example")

    assert "IN THE UNITED STATES DISTRICT COURT" in rendered
    assert "COMPLAINT FOR BREACH OF CONTRACT" in rendered
    assert len(pages) == 2
    assert pages[-1][-1] == "Example  Page 2 of 2"


def test_formal_document_summary_reports_missing_markers_and_validation():
    body = SAMPLE_DOCUMENT + "\nPRAYER FOR RELIEF\nPlaintiff requests relief.\n"

    issues = validate_formal_document(body, required_markers=["MOTION TO COMPEL", "PRAYER FOR RELIEF"])
    summary = summarize_formal_document(body, required_markers=["MOTION TO COMPEL", "PRAYER FOR RELIEF"])

    assert issues == []
    assert summary["is_formally_valid"] is True
    assert summary["formal_sections_present"]["MOTION TO COMPEL"] is True
