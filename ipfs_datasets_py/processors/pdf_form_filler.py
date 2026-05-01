"""PDF form discovery, fillable conversion, and strict field filling.

This module is intentionally dependency-light at import time.  PyMuPDF is only
required by functions that read or write PDFs, while schema inference and
overflow validation remain pure Python and easy to test.

New in this version:
- :func:`classify_pdf` — lightweight document-type classifier.
- :func:`infer_field_data_type` extended with i18n token tables for Spanish,
  French, German, Portuguese and Italian labels.
- Grid/table form field detection (:func:`_fields_from_grid_tables`).
- Radio-group and dropdown detection inside :func:`_fields_from_drawings`.
- XFA (XML Forms Architecture) extraction path (:func:`_fields_from_xfa`).
- ``LayoutProvider`` callback accepted by :func:`analyze_pdf_form`, enabling
  vision-model or rule-based page-layout passes on scanned PDFs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from io import BytesIO
import math
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


Rect = tuple[float, float, float, float]
OCRProvider = Callable[[Any, int], str]
VLMFieldProvider = Callable[[Mapping[str, Any]], Iterable[Mapping[str, Any]]]
# LayoutProvider receives a page-context dict (same schema as vlm_field_provider)
# and returns a sequence of layout-block dicts.  Each block may contain:
#   {"kind": "line"|"table"|"form_region", "rect": [...], "text": "...", ...}
LayoutProvider = Callable[[Mapping[str, Any]], Iterable[Mapping[str, Any]]]


class PDFFormError(RuntimeError):
    """Base exception for PDF form processing errors."""


class PDFFormDependencyError(PDFFormError):
    """Raised when an optional PDF dependency is unavailable."""


class PDFFormFieldError(PDFFormError):
    """Raised when a requested field cannot be found or is invalid."""


class PDFFormTextOverflowError(PDFFormFieldError):
    """Raised when text cannot fit in the target paper or AcroForm field."""


@dataclass(frozen=True)
class FormFieldSpec:
    """Machine-readable description of a field needed by a paper form."""

    name: str
    label: str
    page_index: int
    rect: Rect
    data_type: str = "string"
    required: bool = False
    max_chars: int | None = None
    font_size: float | None = None
    multiline: bool = False
    options: tuple[str, ...] = ()
    source: str = "heuristic"
    confidence: float = 0.5
    dependencies: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rect"] = list(self.rect)
        payload["options"] = list(self.options)
        payload["dependencies"] = list(self.dependencies)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class FormDependencyEdge:
    """Relationship between form fields or between fields and data types."""

    source: str
    target: str
    relation: str
    required: bool = True
    confidence: float = 0.75

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FormDependencyGraph:
    """Dependency graph for the data a form needs to be completed."""

    nodes: Mapping[str, Mapping[str, Any]]
    edges: tuple[FormDependencyEdge, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {node_id: dict(payload) for node_id, payload in self.nodes.items()},
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class FormAnalysisResult:
    """Result returned by :func:`analyze_pdf_form`."""

    source_pdf: str
    fields: tuple[FormFieldSpec, ...]
    dependency_graph: FormDependencyGraph
    page_text: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_pdf": self.source_pdf,
            "fields": [field_spec.to_dict() for field_spec in self.fields],
            "dependency_graph": self.dependency_graph.to_dict(),
            "page_text": list(self.page_text),
            "metadata": dict(self.metadata),
        }


def _require_fitz() -> Any:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised where fitz is absent
        raise PDFFormDependencyError(
            "PyMuPDF is required for PDF form reading and writing. "
            "Install the package with the 'pdf' extra or install pymupdf."
        ) from exc
    return fitz


def normalize_rect(rect: Sequence[float]) -> Rect:
    if len(rect) != 4:
        raise ValueError(f"Expected a 4-coordinate rectangle, got {len(rect)} values")
    x0, y0, x1, y1 = (float(value) for value in rect)
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    return (left, top, right, bottom)


def rect_width(rect: Sequence[float]) -> float:
    x0, _, x1, _ = normalize_rect(rect)
    return max(0.0, x1 - x0)


def rect_height(rect: Sequence[float]) -> float:
    _, y0, _, y1 = normalize_rect(rect)
    return max(0.0, y1 - y0)


_I18N_TOKENS: dict[str, list[tuple[str, str]]] = {
    # (token, data_type) pairs for non-English labels
    "signature": [
        ("firma", "signature"),          # ES/IT
        ("signature", "signature"),      # FR
        ("unterschrift", "signature"),   # DE
        ("assinatura", "signature"),     # PT
    ],
    "email": [
        ("correo electrónico", "email"), # ES
        ("courriel", "email"),           # FR
        ("e-mail", "email"),
    ],
    "phone": [
        ("teléfono", "phone"),           # ES
        ("téléphone", "phone"),          # FR
        ("telefon", "phone"),            # DE
        ("telefone", "phone"),           # PT
    ],
    "date": [
        ("fecha", "date"),               # ES
        ("date", "date"),                # FR
        ("datum", "date"),               # DE
        ("data", "date"),                # PT/IT
        ("naissance", "date"),           # FR (date of birth)
        ("nacimiento", "date"),          # ES (date of birth)
    ],
    "currency": [
        ("importe", "currency"),         # ES
        ("montant", "currency"),         # FR
        ("betrag", "currency"),          # DE
        ("valor", "currency"),           # PT/ES
        ("totale", "currency"),          # IT
        ("salario", "currency"),         # ES/PT
    ],
    "postal_code": [
        ("código postal", "postal_code"), # ES
        ("code postal", "postal_code"),   # FR
        ("postleitzahl", "postal_code"),  # DE
        ("cep", "postal_code"),           # PT
        ("cap", "postal_code"),           # IT
    ],
    "person_name": [
        ("nombre", "person_name"),        # ES
        ("nom", "person_name"),           # FR
        ("name", "person_name"),          # DE (overlaps EN)
        ("nome", "person_name"),          # IT/PT
        ("apellido", "person_name"),      # ES (surname)
        ("prénom", "person_name"),        # FR (first name)
        ("vorname", "person_name"),       # DE (first name)
        ("solicitante", "person_name"),   # ES
    ],
    "address": [
        ("dirección", "address"),         # ES
        ("adresse", "address"),           # FR/DE
        ("endereço", "address"),          # PT
        ("indirizzo", "address"),         # IT
    ],
    "place": [
        ("ciudad", "place"),              # ES
        ("ville", "place"),               # FR
        ("stadt", "place"),               # DE
        ("cidade", "place"),              # PT
        ("città", "place"),               # IT
    ],
}

# Flattened list for O(n) scan
_I18N_FLAT: list[tuple[str, str]] = [
    (token, dtype)
    for pairs in _I18N_TOKENS.values()
    for token, dtype in pairs
]


def infer_field_data_type(label: str, *, options: Sequence[str] = ()) -> str:
    """Infer the data type a form field expects from its label text.

    Supports English labels and a best-effort pass over Spanish, French,
    German, Portuguese, and Italian label tokens.
    """

    text = label.lower()
    if options:
        return "choice"
    if any(token in text for token in ("signature", "sign here", "signed")):
        return "signature"
    if "email" in text or "e-mail" in text:
        return "email"
    if any(token in text for token in ("phone", "telephone", "fax")):
        return "phone"
    if any(token in text for token in ("ssn", "social security")):
        return "ssn"
    if any(token in text for token in ("ein", "taxpayer id", "tax id", "itin")):
        return "tax_identifier"
    if any(token in text for token in ("date", "dob", "birth")):
        return "date"
    if any(token in text for token in ("amount", "income", "wage", "salary", "rent", "total", "$")):
        return "currency"
    if any(token in text for token in ("zip", "postal")):
        return "postal_code"
    if any(token in text for token in ("state", "province")):
        return "state"
    if any(token in text for token in ("city", "county")):
        return "place"
    if "address" in text:
        return "address"
    if any(token in text for token in ("name", "applicant", "taxpayer", "tenant", "landlord")):
        return "person_name"
    if any(token in text for token in ("yes", "no", "check", "box")):
        return "boolean"
    # i18n fallback pass
    for token, dtype in _I18N_FLAT:
        if token in text:
            return dtype
    return "string"


def slugify_field_name(label: str, *, fallback: str = "field") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug or fallback


def estimate_max_chars(rect: Sequence[float], font_size: float = 10.0, *, multiline: bool = False) -> int:
    """Estimate a conservative character capacity for a PDF field rectangle."""

    width = rect_width(rect)
    height = rect_height(rect)
    average_char_width = max(1.0, font_size * 0.52)
    chars_per_line = max(1, int(width // average_char_width))
    if not multiline:
        return chars_per_line
    line_height = max(1.0, font_size * 1.2)
    line_count = max(1, int(height // line_height))
    return chars_per_line * line_count


def validate_text_for_field(value: Any, field_spec: FormFieldSpec) -> str:
    """Return stringified field text or raise if it exceeds field constraints."""

    text = "" if value is None else str(value)
    font_size = float(field_spec.font_size or 10.0)
    max_chars = field_spec.max_chars or estimate_max_chars(
        field_spec.rect,
        font_size,
        multiline=field_spec.multiline,
    )
    if len(text) > max_chars:
        raise PDFFormTextOverflowError(
            f"Value for field '{field_spec.name}' is {len(text)} characters, "
            f"but the field allows at most {max_chars} characters."
        )
    if not field_spec.multiline and _estimate_text_width(text, font_size) > rect_width(field_spec.rect):
        raise PDFFormTextOverflowError(
            f"Value for field '{field_spec.name}' does not fit in the field width "
            f"at font size {font_size:g}."
        )
    if field_spec.multiline:
        line_capacity = estimate_max_chars(field_spec.rect, font_size, multiline=False)
        line_count = max(1, math.ceil(len(text) / max(1, line_capacity)))
        required_height = line_count * font_size * 1.2
        if required_height > rect_height(field_spec.rect):
            raise PDFFormTextOverflowError(
                f"Value for field '{field_spec.name}' needs about {line_count} lines, "
                "which exceeds the field height."
            )
    return text


def _estimate_text_width(text: str, font_size: float) -> float:
    return len(text) * max(1.0, font_size * 0.52)


def build_form_dependency_graph(fields: Sequence[FormFieldSpec]) -> FormDependencyGraph:
    """Create a graph of field requirements, data types, and inferred dependencies."""

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[FormDependencyEdge] = []
    by_type: dict[str, list[FormFieldSpec]] = {}

    for spec in fields:
        nodes[spec.name] = {
            "kind": "field",
            "label": spec.label,
            "data_type": spec.data_type,
            "required": spec.required,
            "page_index": spec.page_index,
            "rect": list(spec.rect),
            "max_chars": spec.max_chars,
            "font_size": spec.font_size,
            "source": spec.source,
            "confidence": spec.confidence,
        }
        type_node = f"type:{spec.data_type}"
        nodes.setdefault(type_node, {"kind": "data_type", "data_type": spec.data_type})
        edges.append(FormDependencyEdge(spec.name, type_node, "expects_type", required=True, confidence=0.95))
        by_type.setdefault(spec.data_type, []).append(spec)

    field_by_name = {field_spec.name: field_spec for field_spec in fields}
    for spec in fields:
        for dependency in spec.dependencies:
            if dependency in field_by_name:
                edges.append(FormDependencyEdge(spec.name, dependency, "depends_on", required=True, confidence=0.9))

    primary_name = _first_field_name(by_type, "person_name")
    primary_address = _first_field_name(by_type, "address")
    for spec in fields:
        label = spec.label.lower()
        if primary_name and spec.name != primary_name and spec.data_type in {"signature", "date"}:
            edges.append(FormDependencyEdge(spec.name, primary_name, "depends_on", required=True, confidence=0.7))
        if primary_address and spec.name != primary_address and spec.data_type in {"place", "state", "postal_code"}:
            edges.append(FormDependencyEdge(spec.name, primary_address, "depends_on", required=True, confidence=0.7))
        if "total" in label:
            for amount_field in by_type.get("currency", ()):
                if amount_field.name != spec.name and "total" not in amount_field.label.lower():
                    edges.append(FormDependencyEdge(spec.name, amount_field.name, "computed_from", required=False, confidence=0.55))

    return FormDependencyGraph(nodes=nodes, edges=tuple(_dedupe_edges(edges)))


def _first_field_name(by_type: Mapping[str, Sequence[FormFieldSpec]], data_type: str) -> str | None:
    fields = by_type.get(data_type) or ()
    return fields[0].name if fields else None


def _dedupe_edges(edges: Iterable[FormDependencyEdge]) -> list[FormDependencyEdge]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[FormDependencyEdge] = []
    for edge in edges:
        key = (edge.source, edge.target, edge.relation)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped


def analyze_pdf_form(
    pdf_path: str | Path,
    *,
    ocr_provider: OCRProvider | None = None,
    layout_provider: LayoutProvider | None = None,
    vlm_field_provider: VLMFieldProvider | None = None,
    include_native_widgets: bool = True,
    include_xfa: bool = True,
    include_heuristics: bool = True,
    include_grid_tables: bool = True,
) -> FormAnalysisResult:
    """Analyze a blank form PDF and infer fields plus a dependency graph.

    Args:
        pdf_path: Path to the PDF file.
        ocr_provider: Supplies page text for scanned pages.  Receives the
            PyMuPDF page object and zero-based page index.
        layout_provider: Returns structured layout blocks (lines, tables,
            form regions) for a page.  Receives a page-context dict identical
            to the one passed to ``vlm_field_provider``.  Each yielded dict
            should carry at least ``{"kind": str, "rect": [...], "text": str}``.
            Useful for integrating a vision-model or rule-based layout engine
            on scanned documents.
        vlm_field_provider: Adds or corrects fields from a vision-language
            model.  Receives the same page-context dict as ``layout_provider``.
        include_native_widgets: Extract AcroForm widget annotations.
        include_xfa: Attempt to extract fields from XFA streams (if present).
        include_heuristics: Run underline and drawing-box heuristics.
        include_grid_tables: Detect fields embedded in grid/table layouts.
    """

    fitz = _require_fitz()
    source = str(pdf_path)
    fields: list[FormFieldSpec] = []
    page_text: list[str] = []

    with fitz.open(source) as document:
        # XFA extraction is document-level
        if include_xfa:
            fields.extend(_fields_from_xfa(document))

        for page_index, page in enumerate(document):
            native_text = page.get_text("text") or ""
            ocr_words: list[dict[str, Any]] = []
            if ocr_provider is not None:
                ocr_text = ocr_provider(page, page_index) or ""
                # Attempt word-level OCR for better spatial heuristics
                ocr_words = _ocr_words_from_provider(ocr_provider, page, page_index)
                text = "\n".join(part for part in (native_text, ocr_text) if part).strip()
            else:
                text = native_text
            page_text.append(text)

            words = _page_words(page)
            # Merge OCR words for scanned pages where native words are sparse
            if ocr_words and len(words) < len(ocr_words) // 2:
                words = ocr_words + words
            drawings = _page_drawing_rects(page)
            page_ctx: dict[str, Any] = {
                "page_index": page_index,
                "text": text,
                "words": words,
                "drawing_rects": drawings,
                "width": float(page.rect.width),
                "height": float(page.rect.height),
            }

            if include_native_widgets:
                fields.extend(_fields_from_widgets(page, page_index))
            if include_heuristics:
                fields.extend(_fields_from_underlines(words, page_index))
                fields.extend(_fields_from_drawings(drawings, words, page_index))
            if include_grid_tables:
                fields.extend(_fields_from_grid_tables(page, words, page_index))
            if layout_provider is not None:
                fields.extend(
                    _fields_from_layout_blocks(
                        layout_provider(page_ctx),
                        words,
                        page_index,
                    )
                )
            if vlm_field_provider is not None:
                fields.extend(
                    _fields_from_vlm(
                        vlm_field_provider(page_ctx),
                        page_index,
                    )
                )

    deduped = tuple(_dedupe_fields(fields))
    graph = build_form_dependency_graph(deduped)
    return FormAnalysisResult(
        source_pdf=source,
        fields=deduped,
        dependency_graph=graph,
        page_text=tuple(page_text),
        metadata={"page_count": len(page_text), "field_count": len(deduped)},
    )


def build_tesseract_ocr_provider(*, dpi: int = 200, lang: str = "eng") -> OCRProvider:
    """Build an OCR provider for :func:`analyze_pdf_form` using pytesseract."""

    try:
        from PIL import Image
        import pytesseract
    except Exception as exc:  # pragma: no cover - depends on optional install
        raise PDFFormDependencyError(
            "pytesseract and Pillow are required for the Tesseract OCR provider."
        ) from exc

    def provider(page: Any, page_index: int) -> str:
        del page_index
        zoom = max(1.0, float(dpi) / 72.0)
        matrix = _require_fitz().Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.open(BytesIO(pixmap.tobytes("png")))
        return str(pytesseract.image_to_string(image, lang=lang) or "")

    return provider


def convert_pdf_to_fillable(
    input_pdf: str | Path,
    output_pdf: str | Path,
    fields: Sequence[FormFieldSpec] | FormAnalysisResult | None = None,
    *,
    overwrite: bool = True,
) -> Path:
    """Create a fillable AcroForm PDF from an ordinary blank paper form."""

    fitz = _require_fitz()
    output_path = Path(output_pdf)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output PDF already exists: {output_path}")
    field_specs = _coerce_fields(input_pdf, fields)

    with fitz.open(str(input_pdf)) as document:
        for spec in field_specs:
            if spec.page_index < 0 or spec.page_index >= len(document):
                raise PDFFormFieldError(f"Field '{spec.name}' references missing page {spec.page_index}")
            page = document[spec.page_index]
            widget = fitz.Widget()
            widget.field_name = spec.name
            widget.field_label = spec.label
            widget.field_type = _widget_type_for_field(fitz, spec)
            widget.rect = fitz.Rect(*spec.rect)
            widget.text_fontsize = float(spec.font_size or 10.0)
            widget.border_width = 0.5
            if spec.data_type == "boolean":
                widget.field_value = False
            page.add_widget(widget)
        document.save(str(output_path), garbage=4, deflate=True)
    return output_path


def fill_pdf_fields(
    input_pdf: str | Path,
    output_pdf: str | Path,
    values: Mapping[str, Any],
    fields: Sequence[FormFieldSpec] | FormAnalysisResult | None = None,
    *,
    strict: bool = True,
    overwrite: bool = True,
) -> Path:
    """Fill PDF fields while enforcing character and field-size limits."""

    fitz = _require_fitz()
    output_path = Path(output_pdf)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output PDF already exists: {output_path}")

    field_specs = {spec.name: spec for spec in _coerce_fields(input_pdf, fields)}
    with fitz.open(str(input_pdf)) as document:
        widget_names = _document_widget_names(document)
        missing = set(values) - set(field_specs) - widget_names
        if strict and missing:
            raise PDFFormFieldError(f"Values reference unknown fields: {', '.join(sorted(missing))}")

        filled_widgets: set[str] = set()
        for page_index, page in enumerate(document):
            for widget in page.widgets() or ():
                name = slugify_field_name(widget.field_name or widget.field_label or "")
                if name not in values:
                    continue
                spec = field_specs.get(name) or _spec_from_widget(name, widget, page_index)
                text = validate_text_for_field(values[name], spec)
                widget.field_value = text
                widget.text_fontsize = float(spec.font_size or widget.text_fontsize or 10.0)
                widget.update()
                filled_widgets.add(name)

        for name, value in values.items():
            if name in filled_widgets:
                continue
            spec = field_specs.get(name)
            if spec is None:
                continue
            text = validate_text_for_field(value, spec)
            page = document[spec.page_index]
            _insert_text_in_rect(page, spec, text)
        document.save(str(output_path), garbage=4, deflate=True)
    return output_path


def _coerce_fields(
    pdf_path: str | Path,
    fields: Sequence[FormFieldSpec] | FormAnalysisResult | None,
) -> tuple[FormFieldSpec, ...]:
    if fields is None:
        return analyze_pdf_form(pdf_path).fields
    if isinstance(fields, FormAnalysisResult):
        return fields.fields
    return tuple(fields)


def _widget_type_for_field(fitz: Any, spec: FormFieldSpec) -> int:
    if spec.data_type == "boolean":
        return int(getattr(fitz, "PDF_WIDGET_TYPE_CHECKBOX", 2))
    return int(getattr(fitz, "PDF_WIDGET_TYPE_TEXT", 7))


def _page_words(page: Any) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for raw in page.get_text("words") or []:
        if len(raw) < 5:
            continue
        x0, y0, x1, y1, text = raw[:5]
        words.append({"rect": normalize_rect((x0, y0, x1, y1)), "text": str(text)})
    return words


def _page_drawing_rects(page: Any) -> list[Rect]:
    rects: list[Rect] = []
    for drawing in page.get_drawings() or []:
        rect = drawing.get("rect") or drawing.get("bbox")
        if rect is None:
            continue
        try:
            rects.append(normalize_rect(tuple(rect)))
        except Exception:
            continue
    return rects


def _fields_from_widgets(page: Any, page_index: int) -> list[FormFieldSpec]:
    fields: list[FormFieldSpec] = []
    for index, widget in enumerate(page.widgets() or ()):
        rect = normalize_rect(tuple(widget.rect))
        label = widget.field_label or widget.field_name or f"Field {index + 1}"
        field_type = str(widget.field_type_string or "").lower()
        data_type = "boolean" if "check" in field_type else infer_field_data_type(label)
        font_size = float(widget.text_fontsize or _font_size_from_rect(rect))
        fields.append(
            FormFieldSpec(
                name=slugify_field_name(widget.field_name or label, fallback=f"page_{page_index + 1}_field_{index + 1}"),
                label=label,
                page_index=page_index,
                rect=rect,
                data_type=data_type,
                max_chars=estimate_max_chars(rect, font_size, multiline=rect_height(rect) > font_size * 1.8),
                font_size=font_size,
                multiline=rect_height(rect) > font_size * 1.8,
                source="acroform",
                confidence=0.98,
            )
        )
    return fields


def _fields_from_underlines(words: Sequence[Mapping[str, Any]], page_index: int) -> list[FormFieldSpec]:
    fields: list[FormFieldSpec] = []
    for index, word in enumerate(words):
        text = str(word.get("text", ""))
        if "_" not in text or len(text) < 4:
            continue
        rect = normalize_rect(word["rect"])
        label = _nearby_label(words, rect) or f"Blank {index + 1}"
        font_size = _font_size_from_rect(rect)
        fields.append(
            _make_field_spec(
                label,
                page_index,
                rect,
                source="underline",
                confidence=0.7,
                font_size=font_size,
                fallback=f"page_{page_index + 1}_blank_{index + 1}",
            )
        )
    return fields


def _fields_from_drawings(
    drawing_rects: Sequence[Rect],
    words: Sequence[Mapping[str, Any]],
    page_index: int,
) -> list[FormFieldSpec]:
    fields: list[FormFieldSpec] = []
    # Separate small checkbox/radio candidates from larger fill boxes
    checkbox_rects: list[Rect] = []
    fill_rects: list[Rect] = []
    for rect in drawing_rects:
        width = rect_width(rect)
        height = rect_height(rect)
        if width < 8 or height < 6 or height > 120:
            continue
        if width <= 20 and height <= 20:
            checkbox_rects.append(rect)
        else:
            fill_rects.append(rect)

    # Cluster checkboxes/radio buttons that share the same vertical band
    radio_groups = _cluster_radio_rects(checkbox_rects)
    for group_index, group in enumerate(radio_groups):
        if len(group) == 1:
            # Single isolated checkbox
            rect = group[0]
            label = _nearby_label(words, rect) or f"Checkbox {group_index + 1}"
            font_size = min(12.0, max(7.0, rect_height(rect) * 0.65))
            fields.append(
                _make_field_spec(
                    label,
                    page_index,
                    rect,
                    source="drawing",
                    confidence=0.6,
                    font_size=font_size,
                    fallback=f"page_{page_index + 1}_checkbox_{group_index + 1}",
                )
            )
        else:
            # Radio group or checkbox group
            group_label = _nearby_label(words, group[0]) or f"Option group {group_index + 1}"
            for option_index, rect in enumerate(group):
                option_label = _nearby_label(words, rect) or f"{group_label} option {option_index + 1}"
                font_size = min(12.0, max(7.0, rect_height(rect) * 0.65))
                fields.append(
                    FormFieldSpec(
                        name=slugify_field_name(option_label, fallback=f"page_{page_index + 1}_radio_{group_index + 1}_{option_index + 1}"),
                        label=option_label,
                        page_index=page_index,
                        rect=rect,
                        data_type="boolean",
                        required=False,
                        max_chars=1,
                        font_size=font_size,
                        source="drawing_radio",
                        confidence=0.65,
                        dependencies=(slugify_field_name(group_label),),
                    )
                )

    for index, rect in enumerate(fill_rects):
        label = _nearby_label(words, rect) or f"Box {index + 1}"
        font_size = min(12.0, max(7.0, rect_height(rect) * 0.65))
        fields.append(
            _make_field_spec(
                label,
                page_index,
                rect,
                source="drawing",
                confidence=0.6,
                font_size=font_size,
                fallback=f"page_{page_index + 1}_box_{index + 1}",
                multiline=rect_height(rect) > 24,
            )
        )
    return fields


def _cluster_radio_rects(rects: Sequence[Rect]) -> list[list[Rect]]:
    """Cluster small checkbox/radio rects that lie on the same horizontal band."""
    if not rects:
        return []
    # Sort by vertical centre
    sorted_rects = sorted(rects, key=lambda r: (r[1] + r[3]) / 2)
    groups: list[list[Rect]] = []
    current_group: list[Rect] = [sorted_rects[0]]
    current_cy = (sorted_rects[0][1] + sorted_rects[0][3]) / 2
    for rect in sorted_rects[1:]:
        cy = (rect[1] + rect[3]) / 2
        if abs(cy - current_cy) <= 16:  # same horizontal band (≈ 16 pt tolerance)
            current_group.append(rect)
        else:
            groups.append(current_group)
            current_group = [rect]
            current_cy = cy
    groups.append(current_group)
    return groups


def _fields_from_vlm(raw_fields: Iterable[Mapping[str, Any]], page_index: int) -> list[FormFieldSpec]:
    fields: list[FormFieldSpec] = []
    for index, raw in enumerate(raw_fields or ()):
        label = str(raw.get("label") or raw.get("name") or f"VLM field {index + 1}")
        rect = normalize_rect(raw.get("rect") or raw.get("bbox") or raw.get("box") or (0, 0, 100, 20))
        font_size = float(raw.get("font_size") or _font_size_from_rect(rect))
        data_type = str(raw.get("data_type") or infer_field_data_type(label, options=raw.get("options") or ()))
        fields.append(
            FormFieldSpec(
                name=slugify_field_name(str(raw.get("name") or label), fallback=f"page_{page_index + 1}_vlm_{index + 1}"),
                label=label,
                page_index=int(raw.get("page_index", page_index)),
                rect=rect,
                data_type=data_type,
                required=bool(raw.get("required", False)),
                max_chars=int(raw["max_chars"]) if raw.get("max_chars") else estimate_max_chars(rect, font_size),
                font_size=font_size,
                multiline=bool(raw.get("multiline", rect_height(rect) > font_size * 1.8)),
                options=tuple(str(option) for option in raw.get("options", ()) or ()),
                source="vlm",
                confidence=float(raw.get("confidence", 0.85)),
                dependencies=tuple(str(item) for item in raw.get("dependencies", ()) or ()),
                metadata={key: value for key, value in raw.items() if key not in {"name", "label", "rect", "bbox", "box"}},
            )
        )
    return fields


def _make_field_spec(
    label: str,
    page_index: int,
    rect: Rect,
    *,
    source: str,
    confidence: float,
    font_size: float,
    fallback: str,
    multiline: bool = False,
) -> FormFieldSpec:
    data_type = infer_field_data_type(label)
    max_chars = estimate_max_chars(rect, font_size, multiline=multiline)
    return FormFieldSpec(
        name=slugify_field_name(label, fallback=fallback),
        label=label,
        page_index=page_index,
        rect=rect,
        data_type=data_type,
        required=_looks_required(label),
        max_chars=max_chars,
        font_size=font_size,
        multiline=multiline,
        source=source,
        confidence=confidence,
    )


def _nearby_label(words: Sequence[Mapping[str, Any]], rect: Rect) -> str:
    x0, y0, _, y1 = rect
    same_line: list[tuple[float, str]] = []
    above: list[tuple[float, str]] = []
    for word in words:
        word_rect = normalize_rect(word["rect"])
        wx0, wy0, wx1, wy1 = word_rect
        text = str(word.get("text", "")).strip()
        if not text or set(text) == {"_"}:
            continue
        vertical_overlap = min(y1, wy1) - max(y0, wy0)
        if vertical_overlap > 0 and wx1 <= x0 + 4 and x0 - wx1 < 180:
            same_line.append((wx0, text))
        elif wy1 <= y0 and y0 - wy1 < 30 and abs(wx0 - x0) < 120:
            above.append((wy0, text))
    candidates = same_line[-6:] if same_line else above[-6:]
    label = " ".join(text for _, text in sorted(candidates))
    return _clean_label(label)


def _clean_label(label: str) -> str:
    label = re.sub(r"[_:.\s]+$", "", label.strip())
    label = re.sub(r"\s+", " ", label)
    return label


def _font_size_from_rect(rect: Rect) -> float:
    return min(12.0, max(7.0, rect_height(rect) * 0.72))


def _looks_required(label: str) -> bool:
    lowered = label.lower()
    return "required" in lowered or "*" in label or "must" in lowered


def _dedupe_fields(fields: Sequence[FormFieldSpec]) -> list[FormFieldSpec]:
    deduped: list[FormFieldSpec] = []
    used_names: dict[str, int] = {}
    for spec in sorted(fields, key=lambda item: (item.page_index, item.rect[1], item.rect[0], -item.confidence)):
        if any(_rects_overlap(spec.rect, existing.rect) > 0.85 and spec.page_index == existing.page_index for existing in deduped):
            continue
        count = used_names.get(spec.name, 0)
        used_names[spec.name] = count + 1
        name = spec.name if count == 0 else f"{spec.name}_{count + 1}"
        deduped.append(FormFieldSpec(**{**spec.to_dict(), "name": name, "rect": tuple(spec.rect)}))
    return deduped


def _rects_overlap(a: Rect, b: Rect) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    intersection = iw * ih
    if intersection <= 0:
        return 0.0
    smaller_area = min(rect_width(a) * rect_height(a), rect_width(b) * rect_height(b))
    return intersection / smaller_area if smaller_area else 0.0


def _document_widget_names(document: Any) -> set[str]:
    names: set[str] = set()
    for page in document:
        for widget in page.widgets() or ():
            name = slugify_field_name(widget.field_name or widget.field_label or "")
            if name:
                names.add(name)
    return names


def _spec_from_widget(name: str, widget: Any | None, page_index: int) -> FormFieldSpec:
    if widget is None:
        raise PDFFormFieldError(f"Missing widget for field '{name}'")
    rect = normalize_rect(tuple(widget.rect))
    label = widget.field_label or widget.field_name or name
    font_size = float(widget.text_fontsize or _font_size_from_rect(rect))
    return FormFieldSpec(
        name=name,
        label=label,
        page_index=page_index,
        rect=rect,
        data_type=infer_field_data_type(label),
        max_chars=estimate_max_chars(rect, font_size),
        font_size=font_size,
        source="acroform",
        confidence=0.98,
    )


def _insert_text_in_rect(page: Any, spec: FormFieldSpec, text: str) -> None:
    fitz = _require_fitz()
    rect = fitz.Rect(*spec.rect)
    font_size = float(spec.font_size or 10.0)
    result = page.insert_textbox(rect, text, fontsize=font_size, fontname="helv", align=0)
    if result < 0:
        raise PDFFormTextOverflowError(f"Value for field '{spec.name}' overflowed the PDF rectangle.")


def _ocr_words_from_provider(
    ocr_provider: OCRProvider,
    page: Any,
    page_index: int,
) -> list[dict[str, Any]]:
    """Attempt to extract word-level bounding boxes from an OCR provider.

    Falls back to an empty list if the provider does not support the
    ``get_words`` mode (most providers only return a plain string).
    """
    try:
        result = ocr_provider(page, page_index)
        if isinstance(result, list):
            words: list[dict[str, Any]] = []
            for item in result:
                if isinstance(item, dict) and "rect" in item and "text" in item:
                    words.append({"rect": normalize_rect(item["rect"]), "text": str(item["text"])})
            return words
    except Exception:
        pass
    return []


def _fields_from_xfa(document: Any) -> list[FormFieldSpec]:
    """Extract form fields from an XFA stream embedded in the PDF.

    XFA (XML Forms Architecture) is used by many government / IRS forms.
    Falls back gracefully when the document has no XFA or when the XML
    cannot be parsed.
    """
    fields: list[FormFieldSpec] = []
    try:
        xfa_data: Any = getattr(document, "get_xfa", lambda: None)()
        if not xfa_data:
            return fields
        # get_xfa() may return bytes or a dict
        xml_bytes: bytes | None = None
        if isinstance(xfa_data, bytes):
            xml_bytes = xfa_data
        elif isinstance(xfa_data, dict):
            # PyMuPDF ≥ 1.23 returns {node_name: bytes, ...}
            for value in xfa_data.values():
                if isinstance(value, bytes) and b"<" in value:
                    xml_bytes = value
                    break
        if not xml_bytes:
            return fields
        fields.extend(_parse_xfa_xml(xml_bytes))
    except Exception:
        pass
    return fields


def _parse_xfa_xml(xml_bytes: bytes) -> list[FormFieldSpec]:
    """Parse XFA XML and extract field specs.  Pure-Python, no extra deps."""
    try:
        import xml.etree.ElementTree as ET  # stdlib
    except ImportError:
        return []

    fields: list[FormFieldSpec] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    # XFA namespace prefixes vary; strip them for tag matching
    _ns_strip = re.compile(r"\{[^}]*\}")

    def _tag(elem: Any) -> str:
        return _ns_strip.sub("", elem.tag)

    def _walk(elem: Any, page_index: int = 0) -> None:
        tag = _tag(elem)
        if tag == "pageArea":
            # Attempt to read page index from parent
            pass
        if tag in ("field", "exclGroup"):
            name_attr = elem.get("name", "")
            # Try to get the caption sub-element
            caption_text = ""
            for child in elem:
                if _tag(child) == "caption":
                    for value_child in child:
                        if _tag(value_child) == "value":
                            for text_child in value_child:
                                caption_text = text_child.text or ""
                                break
                        if not caption_text and value_child.text:
                            caption_text = value_child.text
            label = caption_text.strip() or name_attr or f"xfa_field_{len(fields) + 1}"
            # Infer data type from the field's value/ui child
            data_type = "string"
            for child in elem:
                child_tag = _tag(child)
                if child_tag == "ui":
                    for ui_child in child:
                        ui_tag = _tag(ui_child)
                        if "checkButton" in ui_tag:
                            data_type = "boolean"
                        elif "dateTimeEdit" in ui_tag or "dateField" in ui_tag:
                            data_type = "date"
                        elif "numericEdit" in ui_tag:
                            data_type = "currency"
                        elif "textEdit" in ui_tag:
                            data_type = infer_field_data_type(label)
            if data_type == "string":
                data_type = infer_field_data_type(label)

            # XFA does not reliably encode pixel rects in the XML; use a
            # placeholder rect so the field is still discoverable.
            placeholder_rect: Rect = (0.0, float(len(fields)) * 20.0, 200.0, float(len(fields)) * 20.0 + 18.0)
            fields.append(
                FormFieldSpec(
                    name=slugify_field_name(name_attr or label, fallback=f"xfa_{len(fields) + 1}"),
                    label=label,
                    page_index=page_index,
                    rect=placeholder_rect,
                    data_type=data_type,
                    required=elem.get("presence", "") == "required",
                    source="xfa",
                    confidence=0.9,
                )
            )
        for child in elem:
            _walk(child, page_index)

    _walk(root)
    return fields


def _fields_from_grid_tables(
    page: Any,
    words: Sequence[Mapping[str, Any]],
    page_index: int,
) -> list[FormFieldSpec]:
    """Detect form fields embedded in grid/table layouts.

    Looks for horizontally aligned pairs of (label-cell, value-cell) that
    repeat across rows, which is a common pattern in official government forms.
    """
    fields: list[FormFieldSpec] = []
    try:
        tables = page.find_tables()
    except AttributeError:
        # find_tables() requires PyMuPDF ≥ 1.23.
        return fields
    if not tables:
        return fields

    for table in tables:
        try:
            table_data = table.extract()
        except Exception:
            continue
        if not table_data:
            continue
        # Infer bbox for each cell using the table's cell_rects attribute if available
        cell_rects = getattr(table, "cells", None) or []
        for row_index, row in enumerate(table_data):
            for col_index, cell_text in enumerate(row):
                if not cell_text or not str(cell_text).strip():
                    # Blank cell — likely a fill-in field
                    label = ""
                    # Look left for a label cell
                    if col_index > 0 and row[col_index - 1]:
                        label = str(row[col_index - 1]).strip()
                    # Look above for a header label
                    if not label and row_index > 0 and table_data[row_index - 1]:
                        above = table_data[row_index - 1]
                        if col_index < len(above) and above[col_index]:
                            label = str(above[col_index]).strip()
                    if not label:
                        label = f"cell r{row_index + 1} c{col_index + 1}"

                    # Attempt to get cell rect
                    rect: Rect = (0.0, 0.0, 100.0, 20.0)
                    if cell_rects:
                        flat_index = row_index * len(row) + col_index
                        if flat_index < len(cell_rects) and cell_rects[flat_index]:
                            try:
                                rect = normalize_rect(tuple(cell_rects[flat_index]))
                            except Exception:
                                pass

                    font_size = _font_size_from_rect(rect)
                    fields.append(
                        _make_field_spec(
                            label,
                            page_index,
                            rect,
                            source="grid_table",
                            confidence=0.7,
                            font_size=font_size,
                            fallback=f"page_{page_index + 1}_table_{row_index + 1}_{col_index + 1}",
                        )
                    )
    return fields


def _fields_from_layout_blocks(
    layout_blocks: Iterable[Mapping[str, Any]],
    words: Sequence[Mapping[str, Any]],
    page_index: int,
) -> list[FormFieldSpec]:
    """Create field specs from structured layout blocks supplied by a LayoutProvider."""
    fields: list[FormFieldSpec] = []
    for index, block in enumerate(layout_blocks or ()):
        kind = str(block.get("kind") or "")
        raw_rect = block.get("rect") or block.get("bbox") or block.get("box")
        if raw_rect is None:
            continue
        try:
            rect = normalize_rect(raw_rect)
        except Exception:
            continue
        label = str(block.get("label") or block.get("text") or "").strip()
        if not label:
            label = _nearby_label(words, rect) or f"Layout block {index + 1}"
        font_size = float(block.get("font_size") or _font_size_from_rect(rect))
        data_type = str(block.get("data_type") or infer_field_data_type(label))
        multiline = kind in ("paragraph", "textarea") or rect_height(rect) > font_size * 1.8
        fields.append(
            FormFieldSpec(
                name=slugify_field_name(label, fallback=f"page_{page_index + 1}_layout_{index + 1}"),
                label=label,
                page_index=page_index,
                rect=rect,
                data_type=data_type,
                required=bool(block.get("required", False)),
                max_chars=estimate_max_chars(rect, font_size, multiline=multiline),
                font_size=font_size,
                multiline=multiline,
                source="layout",
                confidence=float(block.get("confidence", 0.75)),
            )
        )
    return fields


# ---------------------------------------------------------------------------
# Document classification
# ---------------------------------------------------------------------------


class PDFDocumentType:
    """Constants for :func:`classify_pdf` return values."""

    FILLABLE_FORM = "fillable_form"
    """AcroForm or XFA with interactive widgets."""
    SCANNED_FORM = "scanned_form"
    """Image-only pages that appear to be a paper form."""
    STRUCTURED_DOCUMENT = "structured_document"
    """Text-rich document (report, contract, etc.) with no detectable form fields."""
    MIXED = "mixed"
    """Combination of the above (e.g., partly scanned, partly interactive)."""


def classify_pdf(
    pdf_path: str | Path,
    *,
    ocr_provider: OCRProvider | None = None,
) -> str:
    """Lightweight heuristic classifier that identifies a PDF's primary type.

    Returns one of the :class:`PDFDocumentType` constants:

    * ``"fillable_form"`` — has AcroForm or XFA widgets.
    * ``"scanned_form"`` — image-only pages with form-like visual structure.
    * ``"structured_document"`` — dense text, no detectable form fields.
    * ``"mixed"`` — cannot be classified as a single type.

    The classification is fast (no OCR by default) and dependency-light.
    Providing an *ocr_provider* enables better detection of scanned forms.
    """
    fitz = _require_fitz()
    source = str(pdf_path)

    has_acroform_widgets = False
    has_xfa = False
    total_pages = 0
    image_only_pages = 0
    form_drawing_pages = 0
    text_rich_pages = 0

    with fitz.open(source) as document:
        total_pages = len(document)
        # Check for XFA
        xfa_data = getattr(document, "get_xfa", lambda: None)()
        has_xfa = bool(xfa_data)

        for page in document:
            widget_list = list(page.widgets() or ())
            if widget_list:
                has_acroform_widgets = True

            native_text = (page.get_text("text") or "").strip()
            images = page.get_images(full=False)

            is_image_only = bool(images) and len(native_text) < 30
            has_drawings = bool(page.get_drawings())

            if is_image_only:
                image_only_pages += 1
            elif len(native_text) > 200:
                text_rich_pages += 1
            if has_drawings and not is_image_only:
                form_drawing_pages += 1

    if has_acroform_widgets or has_xfa:
        return PDFDocumentType.FILLABLE_FORM

    if total_pages == 0:
        return PDFDocumentType.STRUCTURED_DOCUMENT

    image_ratio = image_only_pages / total_pages
    drawing_ratio = form_drawing_pages / total_pages
    text_ratio = text_rich_pages / total_pages

    if image_ratio >= 0.8:
        # Mostly scanned — check if drawings suggest a form
        if drawing_ratio >= 0.3:
            return PDFDocumentType.SCANNED_FORM
        return PDFDocumentType.SCANNED_FORM  # still likely scanned paper form

    if text_ratio >= 0.8 and drawing_ratio < 0.2:
        return PDFDocumentType.STRUCTURED_DOCUMENT

    if drawing_ratio >= 0.4:
        return PDFDocumentType.SCANNED_FORM

    if image_ratio > 0.2 and text_ratio > 0.2:
        return PDFDocumentType.MIXED

    return PDFDocumentType.STRUCTURED_DOCUMENT


__all__ = [
    "FormAnalysisResult",
    "FormDependencyEdge",
    "FormDependencyGraph",
    "FormFieldSpec",
    "LayoutProvider",
    "OCRProvider",
    "PDFDocumentType",
    "PDFFormDependencyError",
    "PDFFormError",
    "PDFFormFieldError",
    "PDFFormTextOverflowError",
    "VLMFieldProvider",
    "analyze_pdf_form",
    "build_form_dependency_graph",
    "build_tesseract_ocr_provider",
    "classify_pdf",
    "convert_pdf_to_fillable",
    "estimate_max_chars",
    "fill_pdf_fields",
    "infer_field_data_type",
    "normalize_rect",
    "slugify_field_name",
    "validate_text_for_field",
]
