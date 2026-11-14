"""GraphRAG over Patent Center / portfolio export artifacts.

Builds a private, local knowledge graph from operator exports:

* Structured nodes/edges from IFW inventory, application metadata, addresses,
  customers, and export receipts (no model required).
* Document text via native PDF text when present, else local Tesseract OCR
  (never remote OCR). Body text is written only under the GraphRAG output
  directory (mode 0600), never to logs.
* Rule-based entity/keyphrase extraction + LogicEnhancedRAG ingest for
  queryable graph retrieval.

Never signs, pays, or files. Does not upload to external services.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from xml.etree import ElementTree as ET

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    default_state_root,
    utc_now_iso,
)

GRAPHRAG_SCHEMA = "patlaw-portfolio-graphrag-v1"

_SAFE_RE = re.compile(r"[^A-Za-z0-9._\-]+")
_APP_RE = re.compile(r"\b(\d{8})\b")
_DOC_CODE_RE = re.compile(r"^([A-Za-z0-9.]+)_(.+)\.pdf$", re.I)


def _safe_id(value: str, *, max_len: int = 120) -> str:
    text = _SAFE_RE.sub("_", str(value or "x")).strip("._") or "x"
    return text[:max_len]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), default=str) + "\n")
            n += 1
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return n


def _flatten_text(value: Any, *, max_chars: int = 200_000) -> str:
    """Serialize structured JSON into plain text for entity extraction."""
    parts: list[str] = []

    def walk(obj: Any, prefix: str = "") -> None:
        if len("".join(parts)) >= max_chars:
            return
        if obj is None:
            return
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                key = str(k)
                if key.lower() in {"token", "password", "secret", "authorization"}:
                    continue
                walk(v, f"{prefix}{key}: " if not prefix else f"{prefix}{key}.")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj[:500]):
                walk(v, f"{prefix}[{i}].")
        else:
            s = str(obj).strip()
            if s and s not in ("None", "null"):
                parts.append(f"{prefix}{s}" if prefix else s)

    walk(value)
    text = "\n".join(parts)
    return text[:max_chars]


def _xml_to_text(path: Path, *, max_chars: int = 200_000) -> str:
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except Exception:
            return ""
    chunks: list[str] = []

    def walk(el: ET.Element, depth: int = 0) -> None:
        if len("".join(chunks)) >= max_chars:
            return
        tag = re.sub(r"\{.*?\}", "", el.tag)
        text = (el.text or "").strip()
        if text:
            chunks.append(f"{tag}: {text}")
        for child in list(el)[:2000]:
            walk(child, depth + 1)

    walk(root)
    return "\n".join(chunks)[:max_chars]


def extract_pdf_text(
    path: Path,
    *,
    enable_ocr: bool = True,
    max_ocr_pages: int = 30,
    ocr_dpi_scale: float = 2.0,
) -> dict[str, Any]:
    """Extract text from a PDF; OCR image-only pages locally when needed."""
    result: dict[str, Any] = {
        "path": str(path),
        "pages": 0,
        "native_chars": 0,
        "ocr_chars": 0,
        "ocr_pages": 0,
        "text": "",
        "method": "none",
        "error": None,
    }
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover
        result["error"] = f"pymupdf_missing:{type(exc).__name__}"
        return result

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        result["error"] = f"open_failed:{type(exc).__name__}"
        return result

    page_texts: list[str] = []
    native_total = 0
    ocr_total = 0
    ocr_pages = 0
    try:
        n_pages = doc.page_count
        result["pages"] = n_pages
        ocr_budget = max(0, int(max_ocr_pages)) if enable_ocr else 0
        for i in range(n_pages):
            page = doc[i]
            native = (page.get_text("text") or "").strip()
            native_total += len(native)
            page_text = native
            if len(native) < 40 and enable_ocr and ocr_budget > 0:
                try:
                    import pytesseract
                    from PIL import Image

                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(ocr_dpi_scale, ocr_dpi_scale),
                        alpha=False,
                    )
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr = (pytesseract.image_to_string(img) or "").strip()
                    if ocr:
                        page_text = ocr if len(ocr) > len(native) else native
                        ocr_total += len(ocr)
                        ocr_pages += 1
                        ocr_budget -= 1
                except Exception:
                    # OCR failure is non-fatal; keep native (possibly empty).
                    pass
            page_texts.append(page_text)
    finally:
        doc.close()

    full = "\n\n".join(t for t in page_texts if t).strip()
    result["text"] = full
    result["native_chars"] = native_total
    result["ocr_chars"] = ocr_total
    result["ocr_pages"] = ocr_pages
    if ocr_pages and native_total:
        result["method"] = "native+ocr"
    elif ocr_pages:
        result["method"] = "ocr"
    elif native_total:
        result["method"] = "native"
    else:
        result["method"] = "empty"
    return result


@dataclass
class GraphNode:
    id: str
    kind: str
    label: str
    props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "props": self.props,
        }


@dataclass
class GraphEdge:
    id: str
    kind: str
    source: str
    target: str
    props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "props": self.props,
        }


@dataclass
class GraphRAGResult:
    schema: str = GRAPHRAG_SCHEMA
    ok: bool = False
    output_dir: str = ""
    applications: list[str] = field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    chunk_count: int = 0
    pdf_processed: int = 0
    ocr_pages: int = 0
    entities_extracted: int = 0
    query_smoke: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    message: str = ""
    generated_at_utc: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "output_dir": self.output_dir,
            "applications": list(self.applications),
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "chunk_count": self.chunk_count,
            "pdf_processed": self.pdf_processed,
            "ocr_pages": self.ocr_pages,
            "entities_extracted": self.entities_extracted,
            "query_smoke": dict(self.query_smoke),
            "errors": list(self.errors),
            "message": self.message,
            "generated_at_utc": self.generated_at_utc or utc_now_iso(),
        }


class PortfolioGraphBuilder:
    """Accumulate nodes/edges/chunks for a portfolio GraphRAG build."""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}
        self.chunks: list[dict[str, Any]] = []

    def add_node(
        self,
        kind: str,
        node_id: str,
        label: str,
        **props: Any,
    ) -> str:
        nid = f"{kind}:{_safe_id(node_id)}"
        if nid not in self.nodes:
            self.nodes[nid] = GraphNode(id=nid, kind=kind, label=label, props=dict(props))
        else:
            self.nodes[nid].props.update({k: v for k, v in props.items() if v is not None})
            if label and not self.nodes[nid].label:
                self.nodes[nid].label = label
        return nid

    def add_edge(
        self,
        kind: str,
        source: str,
        target: str,
        **props: Any,
    ) -> str:
        eid = f"{kind}:{_safe_id(source)}->{_safe_id(target)}"
        if eid not in self.edges:
            self.edges[eid] = GraphEdge(
                id=eid, kind=kind, source=source, target=target, props=dict(props)
            )
        else:
            self.edges[eid].props.update(props)
        return eid

    def add_chunk(
        self,
        *,
        chunk_id: str,
        text: str,
        source_path: str,
        application_number: str = "",
        document_code: str = "",
        kind: str = "text",
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        text = (text or "").strip()
        if not text:
            return
        # Cap chunk size for retrieval friendliness.
        max_len = 12_000
        pieces = [text[i : i + max_len] for i in range(0, len(text), max_len)] or [text]
        for idx, piece in enumerate(pieces):
            row = {
                "chunk_id": f"{chunk_id}:{idx}" if len(pieces) > 1 else chunk_id,
                "kind": kind,
                "application_number": application_number,
                "document_code": document_code,
                "source_path": source_path,
                "text": piece,
                "text_sha256": _sha256_text(piece),
                "char_count": len(piece),
            }
            if extra:
                row.update(dict(extra))
            self.chunks.append(row)


def discover_export_roots(state_root: Path) -> list[Path]:
    """Locate export directories under the portfolio state root."""
    exports = Path(state_root) / "exports"
    if not exports.is_dir():
        return []
    roots = [exports]
    return roots


def iter_application_export_dirs(exports_root: Path) -> Iterator[tuple[str, Path]]:
    """Yield (application_number, app_export_dir) under exports/."""
    if not exports_root.is_dir():
        return
    for child in sorted(exports_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name in {"messages_correspondence", "smoke_test"}:
            # messages_correspondence has applications/ subdir
            apps = child / "applications"
            if apps.is_dir():
                for app_dir in sorted(apps.iterdir()):
                    if app_dir.is_dir() and re.fullmatch(r"\d{7,8}", app_dir.name):
                        yield app_dir.name, app_dir
            continue
        if re.fullmatch(r"\d{7,8}", name):
            yield name, child


def _collect_pdfs(app_dir: Path) -> list[Path]:
    seen: dict[str, Path] = {}
    patterns = (
        "**/files/*.pdf",
        "**/package/*.pdf",
        "**/*.pdf",
    )
    for pat in patterns:
        for p in app_dir.glob(pat):
            if not p.is_file():
                continue
            # Prefer files/ over package/ duplicates by content hash later;
            # de-dupe by filename stem first.
            key = p.name.lower()
            # Prefer paths containing /files/
            if key in seen:
                if "/files/" in str(p).replace("\\", "/") and "/files/" not in str(
                    seen[key]
                ).replace("\\", "/"):
                    seen[key] = p
            else:
                seen[key] = p
    return sorted(seen.values(), key=lambda p: p.name.lower())


def _collect_metadata_json(app_dir: Path) -> list[Path]:
    out: list[Path] = []
    for pat in ("**/metadata/*.json", "**/package/*.json", "**/*summary*.json"):
        for p in app_dir.glob(pat):
            if p.is_file() and p.suffix.lower() == ".json":
                # skip large sealed package duplicates later via hash
                out.append(p)
    # de-dupe by name preferring metadata/
    by_name: dict[str, Path] = {}
    for p in out:
        key = p.name.lower()
        if key in by_name:
            if "/metadata/" in str(p).replace("\\", "/"):
                by_name[key] = p
        else:
            by_name[key] = p
    return sorted(by_name.values(), key=lambda p: p.name.lower())


def _parse_doc_filename(name: str) -> tuple[str, str]:
    m = _DOC_CODE_RE.match(name)
    if m:
        return m.group(1), m.group(2)
    stem = Path(name).stem
    return stem, stem


def _ingest_ifw_inventory(
    builder: PortfolioGraphBuilder,
    app_node: str,
    app: str,
    inventory: Any,
) -> int:
    docs = 0
    bags: list[Any] = []
    if isinstance(inventory, Mapping):
        bags = list(inventory.get("resultBag") or inventory.get("documentBag") or [])
        if bags and isinstance(bags[0], Mapping) and "documentBag" in bags[0]:
            flat = []
            for bag in bags:
                if isinstance(bag, Mapping):
                    flat.extend(bag.get("documentBag") or [])
            bags = flat
    elif isinstance(inventory, list):
        bags = inventory

    for d in bags:
        if not isinstance(d, Mapping):
            continue
        doc_id = str(d.get("documentIdentifier") or "").strip()
        code = str(d.get("documentCode") or "DOC").strip()
        if not doc_id:
            continue
        docs += 1
        desc = str(d.get("documentDescription") or code)
        direction = str(d.get("directionCategory") or "")
        dnode = builder.add_node(
            "document",
            f"{app}:{doc_id}",
            label=f"{code} — {desc}",
            application_number=app,
            document_identifier=doc_id,
            document_code=code,
            document_description=desc,
            direction_category=direction,
            official_date=d.get("officialDate"),
            mime_types=d.get("mimeTypeBag"),
            page_total=d.get("pageTotalQuantity"),
        )
        builder.add_edge("HAS_DOCUMENT", app_node, dnode)
        cnode = builder.add_node("document_code", code, label=code)
        builder.add_edge("HAS_CODE", dnode, cnode)
        if direction:
            dir_node = builder.add_node(
                "direction", direction.upper(), label=direction.upper()
            )
            builder.add_edge("HAS_DIRECTION", dnode, dir_node)
    return docs


def _ingest_application_metadata(
    builder: PortfolioGraphBuilder,
    app: str,
    meta_paths: Sequence[Path],
) -> None:
    app_node = builder.add_node("application", app, label=f"Application {app}")
    for path in meta_paths:
        data = _read_json(path)
        if data is None:
            continue
        name = path.name.lower()

        if "ifw_document_inventory" in name or (
            isinstance(data, Mapping) and data.get("resultBag")
            and "document" in json.dumps(data)[:200].lower()
        ):
            if "inventory" in name or "ifw" in name:
                _ingest_ifw_inventory(builder, app_node, app, data)

        if "address" in name and isinstance(data, Mapping):
            for bag in data.get("resultBag") or []:
                if not isinstance(bag, Mapping):
                    continue
                corr = bag.get("correspondenceAddress") or {}
                if isinstance(corr, Mapping):
                    cn = str(corr.get("customerNumber") or "").strip()
                    addr = corr.get("customerAddress") or {}
                    label_parts = []
                    if isinstance(addr, Mapping):
                        for k in (
                            "nameLineOneText",
                            "addressLineOneText",
                            "cityName",
                            "regionName",
                            "postalCode",
                        ):
                            if addr.get(k):
                                label_parts.append(str(addr[k]))
                    label = ", ".join(label_parts) or f"CN {cn}"
                    anode = builder.add_node(
                        "correspondence_address",
                        f"{app}:{cn or _sha256_text(label)[:12]}",
                        label=label,
                        customer_number=cn,
                        application_number=app,
                    )
                    builder.add_edge("HAS_CORRESPONDENCE_ADDRESS", app_node, anode)
                    if cn:
                        cnode = builder.add_node(
                            "customer_number", cn, label=f"Customer {cn}"
                        )
                        builder.add_edge("HAS_CUSTOMER_NUMBER", app_node, cnode)
                        builder.add_edge("USES_CUSTOMER_NUMBER", anode, cnode)

        if "application_data" in name and isinstance(data, Mapping):
            meta = data.get("applicationMetaData") or data
            if isinstance(meta, Mapping):
                props = {
                    k: meta.get(k)
                    for k in (
                        "patentNumber",
                        "grantDate",
                        "filingDate",
                        "applicationStatusDescriptionText",
                        "applicationStatusCode",
                        "groupArtUnitNumber",
                        "examinerNameText",
                        "inventionTitle",
                        "firstInventorToFileIndicator",
                    )
                    if meta.get(k) is not None
                }
                builder.add_node("application", app, label=f"Application {app}", **props)
                patent = str(meta.get("patentNumber") or "").strip()
                if patent:
                    pnode = builder.add_node(
                        "patent", patent, label=f"Patent {patent}"
                    )
                    builder.add_edge("GRANTED_AS", app_node, pnode)
                examiner = str(meta.get("examinerNameText") or "").strip()
                if examiner:
                    enode = builder.add_node("examiner", examiner, label=examiner)
                    builder.add_edge("HAS_EXAMINER", app_node, enode)
                title = str(meta.get("inventionTitle") or "").strip()
                if title:
                    builder.add_chunk(
                        chunk_id=f"title:{app}",
                        text=f"Invention title for {app}: {title}",
                        source_path=str(path),
                        application_number=app,
                        kind="title",
                    )

        # Always index metadata as a structured text chunk for GraphRAG.
        flat = _flatten_text(data, max_chars=80_000)
        if flat:
            builder.add_chunk(
                chunk_id=f"meta:{app}:{path.stem}",
                text=flat,
                source_path=str(path),
                application_number=app,
                kind="metadata",
            )


def _extract_entities_from_text(
    text: str,
    *,
    domain: str = "patent_prosecution",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rule-based entities + keyphrases (no remote LLM)."""
    entities: list[dict[str, Any]] = []
    keyphrases: list[str] = []
    if not text or len(text.strip()) < 20:
        return entities, keyphrases

    # Lightweight deterministic extractors.
    for m in re.finditer(
        r"\b(?:U\.?S\.?\s*Pat(?:ent)?\.?\s*Nos?\.?|US)\s*([0-9,]{5,})\b",
        text,
        re.I,
    ):
        entities.append(
            {
                "text": m.group(0),
                "type": "patent_reference",
                "value": m.group(1).replace(",", ""),
            }
        )
    for m in re.finditer(r"\b35\s*U\.?S\.?C\.?\s*§?\s*(\d+[a-z]?)\b", text, re.I):
        entities.append(
            {"text": m.group(0), "type": "usc_section", "value": m.group(1)}
        )
    for m in re.finditer(r"\bMPEP\s+§?\s*([\d.]+)\b", text, re.I):
        entities.append(
            {"text": m.group(0), "type": "mpep_section", "value": m.group(1)}
        )
    for m in re.finditer(
        r"\b(Notice of Allowance|Office Action|Final Rejection|Non-Final|"
        r"Issue Notification|Filing Receipt|Information Disclosure Statement|"
        r"Restriction Requirement|Ex Parte Quayle)\b",
        text,
        re.I,
    ):
        entities.append(
            {"text": m.group(1), "type": "mailing_type", "value": m.group(1)}
        )
    for m in re.finditer(r"\bApplication\s*(?:No\.?|Number)?\s*[:#]?\s*(\d{2}[/,]?\d{3},?\d{3}|\d{8})\b", text, re.I):
        entities.append(
            {
                "text": m.group(0),
                "type": "application_number",
                "value": re.sub(r"\D", "", m.group(1)),
            }
        )

    try:
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator,
            OntologyGenerationContext,
            ExtractionStrategy,
            ExtractionConfig,
        )

        gen = OntologyGenerator(use_ipfs_accelerate=False)
        try:
            keyphrases = list(gen.extract_keyphrases(text[:20_000], top_k=20) or [])
        except Exception:
            keyphrases = []
        try:
            ctx = OntologyGenerationContext(
                data_source="portfolio_export",
                data_type="text",
                domain=domain,
                extraction_strategy=ExtractionStrategy.RULE_BASED,
                config=ExtractionConfig(
                    confidence_threshold=0.4,
                    max_entities=80,
                    max_relationships=40,
                ),
            )
            result = gen.extract_entities(text[:30_000], ctx)
            bag = getattr(result, "entities", None) or []
            for ent in bag:
                if hasattr(ent, "name") or hasattr(ent, "text"):
                    entities.append(
                        {
                            "text": str(
                                getattr(ent, "name", None)
                                or getattr(ent, "text", "")
                                or ent
                            ),
                            "type": str(
                                getattr(ent, "type", None)
                                or getattr(ent, "entity_type", "entity")
                            ),
                            "value": str(
                                getattr(ent, "name", None)
                                or getattr(ent, "text", "")
                                or ent
                            ),
                        }
                    )
                elif isinstance(ent, Mapping):
                    entities.append(dict(ent))
                else:
                    entities.append({"text": str(ent), "type": "entity", "value": str(ent)})
        except Exception:
            pass
    except Exception:
        pass

    # de-dupe
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for e in entities:
        key = f"{e.get('type')}:{e.get('value') or e.get('text')}".lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    return uniq, keyphrases


def build_portfolio_graphrag(
    *,
    state_root: Path | None = None,
    application_numbers: Sequence[str] | None = None,
    output_dir: Path | None = None,
    enable_ocr: bool = True,
    max_pdfs_per_app: int = 500,
    max_ocr_pages_per_pdf: int = 200,
    max_ocr_pages_total: int = 2000,
    include_account_alerts: bool = True,
    run_query_smoke: bool = True,
) -> GraphRAGResult:
    """Scan portfolio exports and build a local GraphRAG package."""
    root = Path(state_root) if state_root else default_state_root()
    exports_root = root / "exports"
    out = (
        Path(output_dir)
        if output_dir
        else root / "graphrag" / f"build-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    )
    out.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out, 0o700)
    except OSError:
        pass

    result = GraphRAGResult(output_dir=str(out))
    builder = PortfolioGraphBuilder()
    wanted = {
        re.sub(r"\D", "", str(a))
        for a in (application_numbers or [])
        if re.sub(r"\D", "", str(a))
    }

    # Account-level alerts from messages export
    if include_account_alerts:
        alert_path = (
            exports_root
            / "messages_correspondence"
            / "account"
            / "alert_messages.json"
        )
        if alert_path.is_file():
            data = _read_json(alert_path)
            flat = _flatten_text(data)
            if flat:
                builder.add_node(
                    "account_alerts", "patent_center", label="Patent Center Alerts"
                )
                builder.add_chunk(
                    chunk_id="account:alert_messages",
                    text=flat,
                    source_path=str(alert_path),
                    kind="alert",
                )
            customers = _read_json(
                exports_root
                / "messages_correspondence"
                / "account"
                / "customers.json"
            )
            if isinstance(customers, Mapping):
                for bag in customers.get("customerBag") or []:
                    if not isinstance(bag, Mapping):
                        continue
                    cn = str(bag.get("customerNumber") or "").strip()
                    if cn:
                        builder.add_node(
                            "customer_number", cn, label=f"Customer {cn}"
                        )

    ocr_pages_total = 0
    apps_seen: list[str] = []

    # Group all export directories per application so we only process each app once
    # (e.g. exports/18654466 + exports/messages_correspondence/applications/18654466).
    app_dirs_map: dict[str, list[Path]] = {}
    for app, app_dir in iter_application_export_dirs(exports_root):
        if wanted and app not in wanted:
            continue
        app_dirs_map.setdefault(app, [])
        resolved = app_dir.resolve()
        if not any(resolved == p.resolve() for p in app_dirs_map[app]):
            app_dirs_map[app].append(app_dir)

    for app, app_dirs in sorted(app_dirs_map.items()):
        apps_seen.append(app)
        app_node = builder.add_node("application", app, label=f"Application {app}")

        meta_paths: list[Path] = []
        pdfs: list[Path] = []
        xmls: list[Path] = []
        for d in app_dirs:
            meta_paths.extend(_collect_metadata_json(d))
            pdfs.extend(_collect_pdfs(d))
            xmls.extend(d.glob("**/*.xml"))

        # de-dupe pdfs by content hash
        pdf_by_hash: dict[str, Path] = {}
        for p in pdfs:
            try:
                digest = _sha256_file(p)
            except OSError:
                continue
            if digest not in pdf_by_hash:
                pdf_by_hash[digest] = p
        pdfs = sorted(pdf_by_hash.values(), key=lambda p: p.name.lower())

        # de-dupe metadata by name
        meta_by_name: dict[str, Path] = {}
        for p in meta_paths:
            meta_by_name[p.name.lower()] = p
        meta_paths = sorted(meta_by_name.values(), key=lambda p: p.name.lower())

        _ingest_application_metadata(builder, app, meta_paths)

        for xp in xmls:
            try:
                xt = _xml_to_text(xp)
            except Exception:
                xt = ""
            if xt:
                builder.add_chunk(
                    chunk_id=f"xml:{app}:{xp.stem}",
                    text=xt,
                    source_path=str(xp),
                    application_number=app,
                    kind="xml",
                )
                builder.add_node(
                    "xml_export",
                    f"{app}:{xp.stem}",
                    label=xp.name,
                    application_number=app,
                    path=str(xp),
                )

        # PDF extract + OCR
        for p in pdfs[: max(0, int(max_pdfs_per_app))]:
            remaining_ocr = max(0, int(max_ocr_pages_total) - ocr_pages_total)
            per_pdf_ocr = min(int(max_ocr_pages_per_pdf), remaining_ocr)
            extracted = extract_pdf_text(
                p,
                enable_ocr=enable_ocr and per_pdf_ocr > 0,
                max_ocr_pages=per_pdf_ocr,
            )
            result.pdf_processed += 1
            result.ocr_pages += int(extracted.get("ocr_pages") or 0)
            ocr_pages_total += int(extracted.get("ocr_pages") or 0)

            code, doc_id = _parse_doc_filename(p.name)
            dnode = builder.add_node(
                "document",
                f"{app}:{doc_id}",
                label=f"{code} ({p.name})",
                application_number=app,
                document_code=code,
                document_identifier=doc_id,
                path=str(p),
                sha256=_sha256_file(p) if p.is_file() else None,
                extract_method=extracted.get("method"),
                pages=extracted.get("pages"),
            )
            builder.add_edge("HAS_DOCUMENT", app_node, dnode)
            builder.add_edge(
                "HAS_CODE",
                dnode,
                builder.add_node("document_code", code, label=code),
            )

            text = str(extracted.get("text") or "")
            if text:
                # Persist extracted text privately (not logged).
                text_dir = out / "extracted_text" / app
                text_dir.mkdir(parents=True, exist_ok=True)
                text_path = text_dir / f"{_safe_id(p.stem)}.txt"
                text_path.write_text(text, encoding="utf-8")
                try:
                    os.chmod(text_path, 0o600)
                except OSError:
                    pass

                builder.add_chunk(
                    chunk_id=f"pdf:{app}:{_safe_id(p.stem)}",
                    text=text,
                    source_path=str(p),
                    application_number=app,
                    document_code=code,
                    kind="pdf_text",
                    extra={
                        "extract_method": extracted.get("method"),
                        "ocr_pages": extracted.get("ocr_pages"),
                    },
                )

                ents, kps = _extract_entities_from_text(text)
                result.entities_extracted += len(ents)
                for ent in ents:
                    etype = str(ent.get("type") or "entity")
                    val = str(ent.get("value") or ent.get("text") or "").strip()
                    if not val:
                        continue
                    enode = builder.add_node(
                        etype, f"{app}:{val}", label=val, value=val
                    )
                    builder.add_edge("MENTIONS", dnode, enode)
                for kp in kps[:15]:
                    knode = builder.add_node(
                        "keyphrase", f"{app}:{kp}", label=str(kp)
                    )
                    builder.add_edge("HAS_KEYPHRASE", dnode, knode)
            elif extracted.get("error"):
                result.errors.append(
                    f"pdf_extract:{p.name}:{extracted.get('error')}"
                )

        # Entity extraction over metadata chunks for this app (titles, etc.)
        app_meta_text = "\n".join(
            c["text"]
            for c in builder.chunks
            if c.get("application_number") == app and c.get("kind") == "metadata"
        )[:40_000]
        if app_meta_text:
            ents, kps = _extract_entities_from_text(app_meta_text)
            result.entities_extracted += len(ents)
            for ent in ents:
                val = str(ent.get("value") or ent.get("text") or "").strip()
                if not val:
                    continue
                enode = builder.add_node(
                    str(ent.get("type") or "entity"),
                    f"{app}:{val}",
                    label=val,
                )
                builder.add_edge("MENTIONS", app_node, enode)

    result.applications = apps_seen
    result.node_count = len(builder.nodes)
    result.edge_count = len(builder.edges)
    result.chunk_count = len(builder.chunks)

    # Write graph artifacts
    _write_jsonl(out / "graph-nodes.jsonl", (n.to_dict() for n in builder.nodes.values()))
    _write_jsonl(out / "graph-edges.jsonl", (e.to_dict() for e in builder.edges.values()))
    _write_jsonl(out / "chunks.jsonl", builder.chunks)

    # Compact graph.json (no full chunk bodies — ids only)
    graph_json = {
        "schema": GRAPHRAG_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "applications": apps_seen,
        "nodes": [n.to_dict() for n in builder.nodes.values()],
        "edges": [e.to_dict() for e in builder.edges.values()],
        "chunk_index": [
            {
                "chunk_id": c["chunk_id"],
                "kind": c.get("kind"),
                "application_number": c.get("application_number"),
                "document_code": c.get("document_code"),
                "source_path": c.get("source_path"),
                "char_count": c.get("char_count"),
                "text_sha256": c.get("text_sha256"),
            }
            for c in builder.chunks
        ],
    }
    _write_json(out / "graph.json", graph_json)

    # LogicEnhancedRAG smoke ingest (in-memory; optional persistence of summary)
    if run_query_smoke and builder.chunks:
        try:
            from ipfs_datasets_py.search.logic_integration import LogicEnhancedRAG

            rag = LogicEnhancedRAG(use_neural=False)
            ingested = 0
            # Prefer shorter metadata + mailing chunks first for smoke.
            ordered = sorted(
                builder.chunks,
                key=lambda c: (
                    0
                    if c.get("kind") in {"title", "metadata", "alert"}
                    else 1
                    if c.get("kind") == "pdf_text"
                    else 2,
                    -min(int(c.get("char_count") or 0), 5000),
                ),
            )
            for c in ordered[:40]:
                text = str(c.get("text") or "")
                if len(text) < 40:
                    continue
                # Cap per-doc ingest size.
                rag.ingest_document(text[:8000], str(c["chunk_id"]))
                ingested += 1
            smoke_q = "Notice of Allowance"
            if apps_seen:
                smoke_q = f"What USPTO mailings exist for application {apps_seen[0]}?"
            qres = rag.query(smoke_q, top_k=5)
            result.query_smoke = {
                "ingested_chunks": ingested,
                "query": smoke_q,
                "confidence": getattr(qres, "confidence", None),
                "reasoning_chain": list(getattr(qres, "reasoning_chain", []) or [])[:8],
                "relevant_node_count": len(getattr(qres, "relevant_nodes", []) or []),
            }
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"query_smoke:{type(exc).__name__}:{exc}")
            result.query_smoke = {"ok": False, "error": type(exc).__name__}

    result.ok = bool(result.node_count and (result.chunk_count or result.edge_count))
    result.message = (
        "graphrag_build_complete" if result.ok else "graphrag_build_incomplete"
    )
    result.generated_at_utc = utc_now_iso()
    _write_json(out / "graphrag_receipt.json", result.to_dict())
    # Also drop a pointer under state root
    try:
        latest = root / "graphrag" / "latest_receipt.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(
            json.dumps(
                {
                    "output_dir": str(out),
                    "ok": result.ok,
                    "node_count": result.node_count,
                    "edge_count": result.edge_count,
                    "chunk_count": result.chunk_count,
                    "generated_at_utc": result.generated_at_utc,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(latest, 0o600)
    except Exception:
        pass
    return result


__all__ = [
    "GraphRAGResult",
    "PortfolioGraphBuilder",
    "build_portfolio_graphrag",
    "extract_pdf_text",
]
