from pathlib import Path

import pytest

from ipfs_datasets_py.processors.pdf_form_filler import (
    FormFieldSpec,
    PDFFormTextOverflowError,
    analyze_pdf_form,
    build_form_dependency_graph,
    convert_pdf_to_fillable,
    fill_pdf_fields,
    infer_field_data_type,
    validate_text_for_field,
)


def test_field_type_inference_and_dependency_graph():
    fields = (
        FormFieldSpec(
            name="taxpayer_name",
            label="Taxpayer name",
            page_index=0,
            rect=(100, 100, 260, 114),
            data_type=infer_field_data_type("Taxpayer name"),
        ),
        FormFieldSpec(
            name="signature",
            label="Signature",
            page_index=0,
            rect=(100, 130, 260, 144),
            data_type=infer_field_data_type("Signature"),
        ),
        FormFieldSpec(
            name="total_income",
            label="Total income",
            page_index=0,
            rect=(100, 160, 180, 174),
            data_type=infer_field_data_type("Total income"),
        ),
    )

    graph = build_form_dependency_graph(fields)
    edge_pairs = {(edge.source, edge.target, edge.relation) for edge in graph.edges}

    assert infer_field_data_type("Social Security Number") == "ssn"
    assert infer_field_data_type("Date of birth") == "date"
    assert graph.nodes["taxpayer_name"]["data_type"] == "person_name"
    assert ("signature", "taxpayer_name", "depends_on") in edge_pairs
    assert ("total_income", "type:currency", "expects_type") in edge_pairs


def test_validate_text_for_field_rejects_character_and_width_overflow():
    field = FormFieldSpec(
        name="short_name",
        label="Name",
        page_index=0,
        rect=(0, 0, 30, 12),
        data_type="person_name",
        max_chars=5,
        font_size=10,
    )

    assert validate_text_for_field("Ada", field) == "Ada"
    with pytest.raises(PDFFormTextOverflowError):
        validate_text_for_field("Ada Lovelace", field)


def test_analyze_convert_and_fill_simple_pdf(tmp_path: Path):
    fitz = pytest.importorskip("fitz")

    input_pdf = tmp_path / "blank_form.pdf"
    fillable_pdf = tmp_path / "fillable.pdf"
    filled_pdf = tmp_path / "filled.pdf"

    document = fitz.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 60), "Name:", fontsize=10)
    page.draw_rect(fitz.Rect(90, 48, 220, 66), color=(0, 0, 0), width=0.5)
    document.save(input_pdf)
    document.close()

    analysis = analyze_pdf_form(input_pdf)
    assert any(field.label.lower().startswith("name") for field in analysis.fields)

    name_field = next(field for field in analysis.fields if field.label.lower().startswith("name"))
    fields = (
        FormFieldSpec(
            name="name",
            label="Name",
            page_index=name_field.page_index,
            rect=name_field.rect,
            data_type="person_name",
            max_chars=20,
            font_size=10,
        ),
    )

    convert_pdf_to_fillable(input_pdf, fillable_pdf, fields)
    fill_pdf_fields(fillable_pdf, filled_pdf, {"name": "Ada Lovelace"}, fields)

    with fitz.open(filled_pdf) as filled:
        widgets = list(filled[0].widgets() or ())
        assert widgets
        assert widgets[0].field_value == "Ada Lovelace"
