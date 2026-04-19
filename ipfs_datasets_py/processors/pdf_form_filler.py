"""PDF form discovery, fillable conversion, and strict field filling.

This module is intentionally dependency-light at import time.  PyMuPDF is only
required by functions that read or write PDFs, while schema inference and
overflow validation remain pure Python and easy to test.
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


def infer_field_data_type(label: str, *, options: Sequence[str] = ()) -> str:
    """Infer the data type a form field expects from its label text."""

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
    vlm_field_provider: VLMFieldProvider | None = None,
    include_native_widgets: bool = True,
    include_heuristics: bool = True,
) -> FormAnalysisResult:
    """Analyze a blank form PDF and infer fields plus a dependency graph.

    ``ocr_provider`` can supply page text for scanned pages.  It receives the
    PyMuPDF page object and zero-based page index.  ``vlm_field_provider`` can
    add or correct fields from a vision-language model; it receives a page
    context dictionary with text, words, and drawing rectangles.
    """

    fitz = _require_fitz()
    source = str(pdf_path)
    fields: list[FormFieldSpec] = []
    page_text: list[str] = []

    with fitz.open(source) as document:
        for page_index, page in enumerate(document):
            native_text = page.get_text("text") or ""
            if ocr_provider is not None:
                ocr_text = ocr_provider(page, page_index) or ""
                text = "\n".join(part for part in (native_text, ocr_text) if part).strip()
            else:
                text = native_text
            page_text.append(text)

            words = _page_words(page)
            drawings = _page_drawing_rects(page)
            if include_native_widgets:
                fields.extend(_fields_from_widgets(page, page_index))
            if include_heuristics:
                fields.extend(_fields_from_underlines(words, page_index))
                fields.extend(_fields_from_drawings(drawings, words, page_index))
            if vlm_field_provider is not None:
                fields.extend(
                    _fields_from_vlm(
                        vlm_field_provider(
                            {
                                "page_index": page_index,
                                "text": text,
                                "words": words,
                                "drawing_rects": drawings,
                                "width": float(page.rect.width),
                                "height": float(page.rect.height),
                            }
                        ),
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
    for index, rect in enumerate(drawing_rects):
        width = rect_width(rect)
        height = rect_height(rect)
        if width < 8 or height < 6 or height > 120:
            continue
        label = _nearby_label(words, rect) or f"Box {index + 1}"
        font_size = min(12.0, max(7.0, height * 0.65))
        fields.append(
            _make_field_spec(
                label,
                page_index,
                rect,
                source="drawing",
                confidence=0.6,
                font_size=font_size,
                fallback=f"page_{page_index + 1}_box_{index + 1}",
                multiline=height > 24,
            )
        )
    return fields


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


__all__ = [
    "FormAnalysisResult",
    "FormDependencyEdge",
    "FormDependencyGraph",
    "FormFieldSpec",
    "PDFFormDependencyError",
    "PDFFormError",
    "PDFFormFieldError",
    "PDFFormTextOverflowError",
    "analyze_pdf_form",
    "build_form_dependency_graph",
    "build_tesseract_ocr_provider",
    "convert_pdf_to_fillable",
    "estimate_max_chars",
    "fill_pdf_fields",
    "infer_field_data_type",
    "normalize_rect",
    "slugify_field_name",
    "validate_text_for_field",
]
