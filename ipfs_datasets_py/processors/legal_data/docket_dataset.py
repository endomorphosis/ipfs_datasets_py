"""Docket dataset import and indexing helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import math
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ...logic.deontic import DeonticGraph, DeonticGraphBuilder
from ..protocol import Entity, KnowledgeGraph, Relationship
from .document_structure import parse_legal_document_to_graph
from .docket_packaging import (
    load_packaged_docket_dataset,
    load_packaged_docket_dataset_components,
    package_docket_dataset,
)
from .formal_docket_enrichment import enrich_docket_documents_with_formal_logic
from .proof_assistant import build_docket_proof_assistant
from .rich_docket_enrichment import enrich_docket_documents_with_routers
from ..retrieval import (
    build_bm25_index,
    bm25_search_documents,
    embed_query_for_backend,
    embed_texts_with_router_or_local,
    hashed_term_projection,
    vector_dot,
)


def _utc_now_isoformat() -> str:
    return datetime.now(UTC).isoformat()


def _safe_identifier(value: Any) -> str:
    text = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(value or "")).strip("_")
    return text or "item"


def _dedupe_string_sequence(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _is_generic_dcec_formula(formula: Any) -> bool:
    text = str(formula or "").strip()
    return text.startswith("Happens(DocumentFiled(") or text.startswith("Frame(")


def _is_substantive_temporal_formula(formula: Any) -> bool:
    text = str(formula or "").strip()
    if not text:
        return False
    return any(token in text for token in ("-> O(", "-> P(", "-> F(", "O_", "P_", "F_", "By(t,", "Within(t,", "After(t,", "Before(t,", "During(t,"))


def _is_substantive_dcec_formula(formula: Any) -> bool:
    text = str(formula or "").strip()
    if not text:
        return False
    if _is_generic_dcec_formula(text):
        return False
    return any(
        token in text
        for token in (
            "-> O(",
            "-> P(",
            "-> F(",
            "HoldsAt(Obligated(",
            "HoldsAt(Permitted(",
            "HoldsAt(Forbidden(",
            "forall t (",
        )
    )


def _entity_id(payload: Any) -> str:
    return str((payload or {}).get("id") or "").strip() if isinstance(payload, dict) else ""


def _relationship_id(payload: Any) -> str:
    return str((payload or {}).get("id") or "").strip() if isinstance(payload, dict) else ""


def _is_substantive_kg_entity(entity: Any) -> bool:
    if not isinstance(entity, dict):
        return False
    entity_type = str(entity.get("type") or "").strip().lower()
    return entity_type in {"legal_actor", "court_event", "deadline", "deontic_statement", "structured_deontic_norm"}


def _is_substantive_kg_relationship(relationship: Any) -> bool:
    if not isinstance(relationship, dict):
        return False
    rel_type = str(relationship.get("type") or "").strip().upper()
    return rel_type in {
        "SUBJECT_OF",
        "NORM_SUBJECT",
        "IMPOSES_NORM",
        "HAS_DEADLINE",
        "DEADLINE_FOR",
        "IMPOSES_DEADLINE",
        "SCHEDULES",
        "GRANTS",
        "DENIES",
        "VACATES",
        "CONTINUES",
    }


@dataclass
class DocketDocument:
    """Normalized docket document record."""

    document_id: str
    docket_id: str
    title: str
    text: str
    date_filed: str = ""
    document_number: str = ""
    source_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DocketDatasetObject:
    """Portable docket dataset object with deferred processing artifacts."""

    dataset_id: str
    docket_id: str
    case_name: str
    court: str
    documents: List[DocketDocument] = field(default_factory=list)
    plaintiff_docket: List[Dict[str, Any]] = field(default_factory=list)
    defendant_docket: List[Dict[str, Any]] = field(default_factory=list)
    authorities: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_graph: Dict[str, Any] = field(default_factory=dict)
    deontic_graph: Dict[str, Any] = field(default_factory=dict)
    deontic_triggers: Dict[str, Any] = field(default_factory=dict)
    proof_assistant: Dict[str, Any] = field(default_factory=dict)
    bm25_index: Dict[str, Any] = field(default_factory=dict)
    vector_index: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "docket_id": self.docket_id,
            "case_name": self.case_name,
            "court": self.court,
            "documents": [document.to_dict() for document in self.documents],
            "plaintiff_docket": [dict(item) for item in self.plaintiff_docket],
            "defendant_docket": [dict(item) for item in self.defendant_docket],
            "authorities": [dict(item) for item in self.authorities],
            "knowledge_graph": dict(self.knowledge_graph),
            "deontic_graph": dict(self.deontic_graph),
            "deontic_triggers": dict(self.deontic_triggers),
            "proof_assistant": dict(self.proof_assistant),
            "bm25_index": dict(self.bm25_index),
            "vector_index": dict(self.vector_index),
            "metadata": dict(self.metadata),
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "docket_id": self.docket_id,
            "case_name": self.case_name,
            "court": self.court,
            "document_count": len(self.documents),
            "knowledge_graph_entity_count": len(list((self.knowledge_graph or {}).get("entities") or [])),
            "knowledge_graph_relationship_count": len(list((self.knowledge_graph or {}).get("relationships") or [])),
            "deontic_rule_count": len(list((self.deontic_graph or {}).get("rules") or [])),
            "deontic_trigger_count": len(list((self.deontic_triggers or {}).get("entries") or [])),
            "proof_assistant_work_item_count": len(list((self.proof_assistant or {}).get("agenda") or [])),
            "bm25_document_count": int((self.bm25_index or {}).get("document_count") or 0),
            "vector_document_count": int((self.vector_index or {}).get("document_count") or 0),
            "metadata": dict(self.metadata),
        }

    def append_party_docket_item(self, party: str, item: Dict[str, Any]) -> None:
        normalized_party = str(party or "").strip().lower()
        if normalized_party not in {"plaintiff", "defendant"}:
            raise ValueError("party must be 'plaintiff' or 'defendant'")
        if not isinstance(item, dict):
            raise ValueError("docket item must be a dictionary")
        collection = self.plaintiff_docket if normalized_party == "plaintiff" else self.defendant_docket
        collection.append(dict(item))
        self._refresh_deontic_state()

    def append_authority(self, authority: Dict[str, Any]) -> None:
        if not isinstance(authority, dict):
            raise ValueError("authority must be a dictionary")
        self.authorities.append(dict(authority))
        self._refresh_deontic_state()

    def write_json(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return output_path

    def write_package(
        self,
        output_dir: str | Path,
        *,
        package_name: str | None = None,
        include_car: bool = True,
    ) -> Dict[str, Any]:
        return package_docket_dataset(
            self.to_dict(),
            output_dir,
            package_name=package_name,
            include_car=include_car,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocketDatasetObject":
        return cls(
            dataset_id=str(data.get("dataset_id") or ""),
            docket_id=str(data.get("docket_id") or ""),
            case_name=str(data.get("case_name") or ""),
            court=str(data.get("court") or ""),
            documents=[
                DocketDocument(
                    document_id=str(item.get("document_id") or ""),
                    docket_id=str(item.get("docket_id") or data.get("docket_id") or ""),
                    title=str(item.get("title") or ""),
                    text=str(item.get("text") or ""),
                    date_filed=str(item.get("date_filed") or ""),
                    document_number=str(item.get("document_number") or ""),
                    source_url=str(item.get("source_url") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in list(data.get("documents") or [])
                if isinstance(item, dict)
            ],
            plaintiff_docket=[dict(item) for item in list(data.get("plaintiff_docket") or []) if isinstance(item, dict)],
            defendant_docket=[dict(item) for item in list(data.get("defendant_docket") or []) if isinstance(item, dict)],
            authorities=[dict(item) for item in list(data.get("authorities") or []) if isinstance(item, dict)],
            knowledge_graph=dict(data.get("knowledge_graph") or {}),
            deontic_graph=dict(data.get("deontic_graph") or {}),
            deontic_triggers=dict(data.get("deontic_triggers") or {}),
            proof_assistant=dict(data.get("proof_assistant") or {}),
            bm25_index=dict(data.get("bm25_index") or {}),
            vector_index=dict(data.get("vector_index") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "DocketDatasetObject":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_package(cls, manifest_path: str | Path) -> "DocketDatasetObject":
        return cls.from_dict(load_packaged_docket_dataset(manifest_path))

    @classmethod
    def from_packaged_components(
        cls,
        manifest_path: str | Path,
        *,
        piece_ids: Sequence[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        return load_packaged_docket_dataset_components(manifest_path, piece_ids=piece_ids)

    def _refresh_deontic_state(self) -> None:
        graph, triggers = build_docket_deontic_artifacts(
            dataset_id=self.dataset_id,
            docket_id=self.docket_id,
            plaintiff_docket=self.plaintiff_docket,
            defendant_docket=self.defendant_docket,
            authorities=self.authorities,
        )
        self.deontic_graph = graph.to_dict()
        self.deontic_triggers = triggers
        self.proof_assistant = build_docket_proof_assistant(
            dataset_id=self.dataset_id,
            docket_id=self.docket_id,
            case_name=self.case_name,
            court=self.court,
            documents=self.documents,
            plaintiff_docket=self.plaintiff_docket,
            defendant_docket=self.defendant_docket,
            authorities=self.authorities,
            knowledge_graph=self.knowledge_graph,
            deontic_graph=self.deontic_graph,
            deontic_triggers=self.deontic_triggers,
            bm25_index=self.bm25_index,
            vector_index=self.vector_index,
        )
        artifact_status = self.metadata.setdefault("artifact_status", {})
        artifact_status["deontic_graph"] = bool(self.deontic_graph)
        artifact_status["deontic_triggers"] = bool(self.deontic_triggers)
        artifact_status["proof_assistant"] = bool(self.proof_assistant)
        self.metadata["last_deontic_refresh"] = _utc_now_isoformat()


class DocketDatasetBuilder:
    """Import an entire docket and build deferred retrieval artifacts."""

    def __init__(self, *, vector_dimension: int = 32, router_max_documents: int | None = 3) -> None:
        self.vector_dimension = max(8, int(vector_dimension))
        self.router_max_documents = None if router_max_documents is None else max(1, int(router_max_documents))

    def build_from_docket(
        self,
        docket: Dict[str, Any],
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
    ) -> DocketDatasetObject:
        normalized_documents = self._normalize_documents(docket)
        docket_id = str(docket.get("docket_id") or docket.get("id") or "docket")
        case_name = str(docket.get("case_name") or docket.get("title") or docket_id)
        court = str(docket.get("court") or docket.get("court_full_name") or "")
        dataset_id = f"docket_dataset_{_safe_identifier(docket_id)}"
        plaintiff_docket = self._normalize_auxiliary_items(docket.get("plaintiff_docket") or docket.get("plaintiffs_docket") or [])
        defendant_docket = self._normalize_auxiliary_items(docket.get("defendant_docket") or docket.get("defendants_docket") or [])
        authorities = self._normalize_auxiliary_items(docket.get("authorities") or docket.get("authorities_list") or [])

        knowledge_graph = self._build_knowledge_graph(dataset_id, docket_id, case_name, court, normalized_documents) if include_knowledge_graph else {}
        deontic_graph_object, deontic_triggers = build_docket_deontic_artifacts(
            dataset_id=dataset_id,
            docket_id=docket_id,
            plaintiff_docket=plaintiff_docket,
            defendant_docket=defendant_docket,
            authorities=authorities,
            explicit_statements=list(docket.get("deontic_statements") or []),
        )
        bm25_index = self._build_bm25_index(dataset_id, normalized_documents) if include_bm25 else {}
        vector_index = self._build_vector_index(dataset_id, normalized_documents) if include_vector_index else {}
        proof_assistant = build_docket_proof_assistant(
            dataset_id=dataset_id,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            documents=normalized_documents,
            plaintiff_docket=plaintiff_docket,
            defendant_docket=defendant_docket,
            authorities=authorities,
            knowledge_graph=knowledge_graph,
            deontic_graph=deontic_graph_object.to_dict(),
            deontic_triggers=deontic_triggers,
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        formal_enrichment = enrich_docket_documents_with_formal_logic(
            normalized_documents,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            max_documents=None,
        )
        self._merge_router_enrichment(
            documents=normalized_documents,
            knowledge_graph=knowledge_graph,
            proof_assistant=proof_assistant,
            router_enrichment=formal_enrichment,
        )
        router_enrichment = enrich_docket_documents_with_routers(
            normalized_documents,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            max_documents=self.router_max_documents,
        )
        self._merge_router_enrichment(
            documents=normalized_documents,
            knowledge_graph=knowledge_graph,
            proof_assistant=proof_assistant,
            router_enrichment=router_enrichment,
        )
        artifact_provenance = {
            "knowledge_graph": {"backend": "parsed_document_structure_graph", "is_mock": False},
            "bm25_index": {"backend": "local_bm25", "is_mock": False},
            "vector_index": {
                "backend": str(vector_index.get("backend") or "local_hashed_term_projection"),
                "provider": str(vector_index.get("provider") or ""),
                "model_name": str(vector_index.get("model_name") or ""),
                "is_mock": False,
            },
            "formal_logic": dict((formal_enrichment.get("summary") or {})),
            "router_enrichment": dict((router_enrichment.get("summary") or {})),
        }
        artifact_status = {
            "knowledge_graph": bool(knowledge_graph),
            "deontic_graph": bool(deontic_graph_object.rules),
            "deontic_triggers": bool((deontic_triggers or {}).get("entries")),
            "proof_assistant": bool((proof_assistant or {}).get("agenda")),
            "bm25_index": bool(bm25_index),
            "vector_index": bool(vector_index),
            "formal_logic": bool((formal_enrichment.get("summary") or {}).get("processed_document_count")),
            "router_enrichment": bool((router_enrichment.get("summary") or {}).get("processed_document_count")),
        }

        return DocketDatasetObject(
            dataset_id=dataset_id,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            documents=normalized_documents,
            plaintiff_docket=plaintiff_docket,
            defendant_docket=defendant_docket,
            authorities=authorities,
            knowledge_graph=knowledge_graph,
            deontic_graph=deontic_graph_object.to_dict(),
            deontic_triggers=deontic_triggers,
            proof_assistant=proof_assistant,
            bm25_index=bm25_index,
            vector_index=vector_index,
            metadata={
                "imported_at": _utc_now_isoformat(),
                "document_count": len(normalized_documents),
                "artifact_provenance": artifact_provenance,
                "artifact_status": artifact_status,
                "source_type": str(docket.get("source_type") or "docket"),
            },
        )

    def build_from_json_file(
        self,
        path: str | Path,
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
    ) -> DocketDatasetObject:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Docket JSON payload must be an object")
        payload.setdefault("source_type", "json_file")
        payload.setdefault("source_path", str(Path(path)))
        return self.build_from_docket(
            payload,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )

    def build_from_directory(
        self,
        directory: str | Path,
        *,
        docket_id: Optional[str] = None,
        case_name: Optional[str] = None,
        court: str = "",
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
        glob_pattern: str = "*",
    ) -> DocketDatasetObject:
        root = Path(directory)
        if not root.exists():
            raise FileNotFoundError(f"Docket directory not found: {root}")
        if not root.is_dir():
            raise ValueError(f"Docket import path is not a directory: {root}")

        documents: List[Dict[str, Any]] = []
        supported_suffixes = {".txt", ".md", ".json"}
        for path in sorted(candidate for candidate in root.rglob(glob_pattern) if candidate.is_file()):
            if path.suffix.lower() not in supported_suffixes:
                continue
            if path.suffix.lower() == ".json":
                json_payload = self._load_json_document_candidate(path)
                if json_payload is not None:
                    documents.append(json_payload)
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            documents.append(
                {
                    "id": path.stem,
                    "title": path.stem.replace("_", " ").replace("-", " ").strip() or path.name,
                    "text": text,
                    "source_url": str(path),
                    "document_type": path.suffix.lower().lstrip("."),
                    "source_path": str(path),
                }
            )

        docket_payload = {
            "docket_id": docket_id or root.name,
            "case_name": case_name or root.name.replace("_", " ").replace("-", " "),
            "court": court,
            "documents": documents,
            "source_type": "directory",
            "source_path": str(root),
        }
        return self.build_from_docket(
            docket_payload,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )

    def _normalize_documents(self, docket: Dict[str, Any]) -> List[DocketDocument]:
        documents_payload = list(docket.get("documents") or docket.get("entries") or [])
        docket_id = str(docket.get("docket_id") or docket.get("id") or "docket")
        normalized: List[DocketDocument] = []
        for index, item in enumerate(documents_payload, start=1):
            if not isinstance(item, dict):
                continue
            text = str(
                item.get("text")
                or item.get("plain_text")
                or item.get("content")
                or item.get("description")
                or ""
            ).strip()
            title = str(item.get("title") or item.get("description") or f"Docket document {index}").strip()
            document_id = str(item.get("document_id") or item.get("id") or f"{docket_id}_doc_{index}")
            existing_metadata = dict(item.get("metadata") or {})
            classification = self._classify_document(title=title, text=text, item=item)
            text_extraction = dict(existing_metadata.get("text_extraction") or {})
            if not text_extraction:
                if str(item.get("document_type") or "") == "courtlistener_docket_summary":
                    text_extraction = {"source": "synthesized_docket_summary"}
                elif str(item.get("document_type") or "") == "courtlistener_docket_entry":
                    text_extraction = {"source": "synthesized_docket_entry"}
            normalized.append(
                DocketDocument(
                    document_id=document_id,
                    docket_id=docket_id,
                    title=title,
                    text=text,
                    date_filed=str(item.get("date_filed") or item.get("filed") or ""),
                    document_number=str(item.get("document_number") or item.get("entry_number") or ""),
                    source_url=str(item.get("source_url") or item.get("recap_url") or item.get("docket_url") or ""),
                    metadata={
                        **existing_metadata,
                        "document_type": item.get("document_type"),
                        "page_count": item.get("page_count"),
                        "text_extraction": text_extraction,
                        "classification": classification,
                        "raw": dict(item),
                    },
                )
            )
        return normalized

    def _classify_document(self, *, title: str, text: str, item: Dict[str, Any]) -> Dict[str, Any]:
        combined = f"{title}\n{text}".lower()
        document_type = str(item.get("document_type") or "").strip().lower()

        rules = [
            ("complaint", ("complaint", "petition")),
            ("answer", ("answer",)),
            ("motion", ("motion",)),
            ("order", ("order", "text order")),
            ("notice", ("notice",)),
            ("summons", ("summons",)),
            ("declaration", ("declaration", "affidavit")),
            ("exhibit", ("exhibit",)),
            ("memorandum", ("memorandum", "memo in support")),
        ]
        for label, keywords in rules:
            if document_type == label or any(keyword in combined for keyword in keywords):
                return {"label": label, "backend": "heuristic_legal_document_classifier", "confidence": 0.6}

        if document_type:
            return {"label": document_type, "backend": "heuristic_legal_document_classifier", "confidence": 0.5}
        return {"label": "other", "backend": "heuristic_legal_document_classifier", "confidence": 0.2}

    def _normalize_auxiliary_items(self, items: Sequence[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(list(items), start=1):
            if isinstance(item, dict):
                payload = dict(item)
            else:
                payload = {"text": str(item)}
            payload.setdefault("id", f"aux_{index}")
            payload.setdefault("title", str(payload.get("label") or payload.get("title") or payload.get("text") or payload.get("id")))
            payload.setdefault("text", str(payload.get("text") or payload.get("description") or payload.get("title") or ""))
            normalized.append(payload)
        return normalized

    def _load_json_document_candidate(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if any(key in payload for key in {"text", "plain_text", "content", "description"}):
            return {
                "id": str(payload.get("document_id") or payload.get("id") or path.stem),
                "title": str(payload.get("title") or payload.get("description") or path.stem),
                "text": str(
                    payload.get("text")
                    or payload.get("plain_text")
                    or payload.get("content")
                    or payload.get("description")
                    or ""
                ),
                "date_filed": str(payload.get("date_filed") or payload.get("filed") or ""),
                "document_number": str(payload.get("document_number") or payload.get("entry_number") or ""),
                "source_url": str(payload.get("source_url") or path),
                "document_type": str(payload.get("document_type") or "json"),
                "source_path": str(path),
            }
        return None

    def _build_knowledge_graph(
        self,
        dataset_id: str,
        docket_id: str,
        case_name: str,
        court: str,
        documents: Sequence[DocketDocument],
    ) -> Dict[str, Any]:
        graph = KnowledgeGraph(source=dataset_id)
        docket_node_id = f"{dataset_id}:docket"
        graph.add_entity(
            Entity(
                id=docket_node_id,
                type="docket",
                label=case_name,
                properties={"docket_id": docket_id, "court": court},
            )
        )

        for document in documents:
            document_node_id = f"{dataset_id}:document:{_safe_identifier(document.document_id)}"
            graph.add_entity(
                Entity(
                    id=document_node_id,
                    type="docket_document",
                    label=document.title,
                    properties={
                        "document_id": document.document_id,
                        "docket_id": document.docket_id,
                        "date_filed": document.date_filed,
                        "document_number": document.document_number,
                        "source_url": document.source_url,
                    },
                )
            )
            graph.add_relationship(
                Relationship(
                    id=f"{dataset_id}:rel:docket_contains:{_safe_identifier(document.document_id)}",
                    source=docket_node_id,
                    target=document_node_id,
                    type="CONTAINS_DOCUMENT",
                )
            )

            if document.text:
                parsed = parse_legal_document_to_graph(document.text, graph_id=f"{dataset_id}:{_safe_identifier(document.document_id)}")
                for node in list(parsed["knowledge_graph"].get("nodes") or []):
                    graph.add_entity(
                        Entity(
                            id=str(node.get("id") or ""),
                            type=str(node.get("type") or "document_node"),
                            label=str(node.get("label") or ""),
                            properties=dict(node.get("properties") or {}),
                        )
                    )
                    graph.add_relationship(
                        Relationship(
                            id=f"{document_node_id}:rel:describes:{_safe_identifier(node.get('id'))}",
                            source=document_node_id,
                            target=str(node.get("id") or ""),
                            type="DESCRIBES",
                        )
                    )
                for edge in list(parsed["knowledge_graph"].get("edges") or []):
                    graph.add_relationship(
                        Relationship(
                            id=f"{dataset_id}:edge:{_safe_identifier(edge.get('source'))}:{_safe_identifier(edge.get('target'))}:{_safe_identifier(edge.get('type'))}",
                            source=str(edge.get("source") or ""),
                            target=str(edge.get("target") or ""),
                            type=str(edge.get("type") or "RELATED_TO").upper(),
                        )
                    )
        return graph.to_dict()

    def _merge_router_enrichment(
        self,
        *,
        documents: Sequence[DocketDocument],
        knowledge_graph: Dict[str, Any],
        proof_assistant: Dict[str, Any],
        router_enrichment: Dict[str, Any],
    ) -> None:
        analyses = dict(router_enrichment.get("document_analyses") or {})
        for document in documents:
            analysis = analyses.get(str(document.document_id))
            if analysis:
                document.metadata["rich_analysis"] = dict(analysis)
                classification = dict((analysis.get("classification") or {}))
                if classification:
                    document.metadata["classification_router"] = classification

        enrichment_kg = dict(router_enrichment.get("knowledge_graph") or {})
        knowledge_graph.setdefault("entities", [])
        knowledge_graph.setdefault("relationships", [])
        existing_entity_ids = {str(item.get("id") or "") for item in list(knowledge_graph.get("entities") or []) if isinstance(item, dict)}
        existing_rel_ids = {str(item.get("id") or "") for item in list(knowledge_graph.get("relationships") or []) if isinstance(item, dict)}
        for entity in list(enrichment_kg.get("entities") or []):
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("id") or "")
            if entity_id and entity_id not in existing_entity_ids:
                knowledge_graph["entities"].append(dict(entity))
                existing_entity_ids.add(entity_id)
        for relationship in list(enrichment_kg.get("relationships") or []):
            if not isinstance(relationship, dict):
                continue
            rel_id = str(relationship.get("id") or "")
            if rel_id and rel_id not in existing_rel_ids:
                knowledge_graph["relationships"].append(dict(relationship))
                existing_rel_ids.add(rel_id)

        proof_assistant.setdefault("metadata", {})
        proof_assistant["metadata"]["router_enrichment"] = dict(router_enrichment.get("summary") or {})
        if router_enrichment.get("deontic_conflicts"):
            proof_assistant["metadata"]["deontic_conflicts"] = list(router_enrichment.get("deontic_conflicts") or [])
        proof_store = dict(router_enrichment.get("proof_store") or {})
        if (proof_store.get("proofs") or proof_store.get("certificates")):
            proof_assistant["proof_store"] = proof_store
        temporal = proof_assistant.setdefault("temporal_fol", {})
        temporal.setdefault("formulas", [])
        substantive_temporal = list(((router_enrichment.get("temporal_fol") or {}).get("formulas") or []))
        existing_temporal = list(temporal.get("formulas") or [])
        temporal["formulas"] = _dedupe_string_sequence(substantive_temporal + existing_temporal)
        proof_assistant["deontic_temporal_first_order_logic"] = dict(temporal)
        dcec = proof_assistant.setdefault("deontic_cognitive_event_calculus", {})
        dcec.setdefault("formulas", [])
        substantive_dcec = list(((router_enrichment.get("deontic_cognitive_event_calculus") or {}).get("formulas") or []))
        existing_dcec = list(dcec.get("formulas") or [])
        substantive_dcec_non_generic = [formula for formula in substantive_dcec if _is_substantive_dcec_formula(formula)]
        substantive_dcec_generic = [formula for formula in substantive_dcec if not _is_substantive_dcec_formula(formula)]
        existing_dcec_non_generic = [formula for formula in existing_dcec if _is_substantive_dcec_formula(formula)]
        existing_dcec_generic = [formula for formula in existing_dcec if not _is_substantive_dcec_formula(formula)]
        dcec["formulas"] = _dedupe_string_sequence(
            substantive_dcec_non_generic
            + existing_dcec_non_generic
            + substantive_dcec_generic
            + existing_dcec_generic
        )
        frames = proof_assistant.setdefault("frames", {})
        substantive_frames = dict(router_enrichment.get("frame_logic") or {})
        combined_frames: Dict[str, Any] = {}
        combined_frames.update(substantive_frames)
        for frame_id, frame_payload in dict(frames).items():
            combined_frames.setdefault(frame_id, frame_payload)
        frames.clear()
        frames.update(combined_frames)
        proof_assistant["frame_logic"] = dict(frames)
        proof_kg = proof_assistant.setdefault("knowledge_graph", {})
        proof_kg.setdefault("entities", [])
        proof_kg.setdefault("relationships", [])
        proof_kg["entities"] = list(
            dict.fromkeys(
                [
                    json.dumps(item, sort_keys=True)
                    for item in list(proof_kg.get("entities") or []) + list(enrichment_kg.get("entities") or [])
                ]
            )
        )
        proof_kg["entities"] = [json.loads(item) for item in proof_kg["entities"]]
        proof_kg["relationships"] = list(
            dict.fromkeys(
                [
                    json.dumps(item, sort_keys=True)
                    for item in list(proof_kg.get("relationships") or [])
                    + list(enrichment_kg.get("relationships") or [])
                ]
            )
        )
        proof_kg["relationships"] = [json.loads(item) for item in proof_kg["relationships"]]
        metadata = proof_assistant.setdefault("metadata", {})
        prior_document_frame_logic = dict(metadata.get("document_frame_logic") or {})
        prior_substantive_views = dict(metadata.get("substantive_views") or {})
        prior_generic_views = dict(metadata.get("generic_views") or {})
        metadata["document_frame_logic"] = dict(prior_document_frame_logic)
        metadata["document_frame_logic"].update(dict(router_enrichment.get("document_frame_logic") or {}))
        combined_substantive_temporal = _dedupe_string_sequence(
            list(prior_substantive_views.get("temporal_formulas") or []) + list(substantive_temporal)
        )
        combined_substantive_dcec = _dedupe_string_sequence(
            list(prior_substantive_views.get("dcec_formulas") or []) + list(substantive_dcec_non_generic)
        )
        combined_substantive_frame_ids = _dedupe_string_sequence(
            list(prior_substantive_views.get("frame_ids") or []) + list(substantive_frames.keys())
        )
        combined_substantive_entity_ids = _dedupe_string_sequence(
            list(prior_substantive_views.get("knowledge_graph_entity_ids") or [])
            + [_entity_id(item) for item in list(enrichment_kg.get("entities") or []) if _is_substantive_kg_entity(item)]
        )
        combined_substantive_relationship_ids = _dedupe_string_sequence(
            list(prior_substantive_views.get("knowledge_graph_relationship_ids") or [])
            + [_relationship_id(item) for item in list(enrichment_kg.get("relationships") or []) if _is_substantive_kg_relationship(item)]
        )
        combined_generic_temporal = _dedupe_string_sequence(
            list(prior_generic_views.get("temporal_formulas") or [])
            + [formula for formula in list(temporal.get("formulas") or []) if not _is_substantive_temporal_formula(formula)]
        )
        combined_generic_dcec = _dedupe_string_sequence(
            list(prior_generic_views.get("dcec_formulas") or [])
            + substantive_dcec_generic
            + existing_dcec_generic
        )
        combined_generic_entity_ids = _dedupe_string_sequence(
            list(prior_generic_views.get("knowledge_graph_entity_ids") or [])
            + [_entity_id(item) for item in list(proof_kg.get("entities") or []) if not _is_substantive_kg_entity(item)]
        )
        combined_generic_relationship_ids = _dedupe_string_sequence(
            list(prior_generic_views.get("knowledge_graph_relationship_ids") or [])
            + [_relationship_id(item) for item in list(proof_kg.get("relationships") or []) if not _is_substantive_kg_relationship(item)]
        )
        metadata["substantive_views"] = {
            "temporal_formulas": combined_substantive_temporal,
            "dcec_formulas": combined_substantive_dcec,
            "frame_ids": combined_substantive_frame_ids,
            "knowledge_graph_entity_ids": combined_substantive_entity_ids,
            "knowledge_graph_relationship_ids": combined_substantive_relationship_ids,
        }
        metadata["generic_views"] = {
            "temporal_formulas": combined_generic_temporal,
            "dcec_formulas": combined_generic_dcec,
            "knowledge_graph_entity_ids": combined_generic_entity_ids,
            "knowledge_graph_relationship_ids": combined_generic_relationship_ids,
        }
        summary = proof_assistant.setdefault("summary", {})
        summary["router_enriched_proof_count"] = int(
            (((proof_assistant.get("proof_store") or {}).get("summary") or {}).get("proof_count") or 0)
        )
        summary["temporal_formula_count"] = len(list((temporal.get("formulas") or [])))
        summary["substantive_temporal_formula_count"] = len(list(combined_substantive_temporal))
        summary["dcec_formula_count"] = len(list((dcec.get("formulas") or [])))
        summary["substantive_dcec_formula_count"] = len(list(combined_substantive_dcec))
        summary["frame_count"] = len(frames)
        summary["substantive_frame_count"] = len(list(combined_substantive_frame_ids))
        summary["proof_knowledge_graph_entity_count"] = len(list((proof_kg.get("entities") or [])))
        summary["proof_knowledge_graph_relationship_count"] = len(list((proof_kg.get("relationships") or [])))
        summary["substantive_proof_knowledge_graph_entity_count"] = len(list(combined_substantive_entity_ids))
        summary["substantive_proof_knowledge_graph_relationship_count"] = len(list(combined_substantive_relationship_ids))
        extractors = proof_assistant.setdefault("extractors", {})
        extractors.setdefault("deontic_temporal_first_order_logic", {})["formula_count"] = len(list((temporal.get("formulas") or [])))
        extractors.setdefault("deontic_temporal_first_order_logic", {})["substantive_formula_count"] = len(list(combined_substantive_temporal))
        extractors.setdefault("deontic_cognitive_event_calculus", {})["formula_count"] = len(list((dcec.get("formulas") or [])))
        extractors.setdefault("deontic_cognitive_event_calculus", {})["substantive_formula_count"] = len(list(combined_substantive_dcec))
        extractors.setdefault("frame_logic", {})["frame_count"] = len(frames)
        extractors.setdefault("frame_logic", {})["substantive_frame_count"] = len(list(combined_substantive_frame_ids))
        extractors.setdefault("knowledge_graph", {})["entity_count"] = len(list((proof_kg.get("entities") or [])))
        extractors.setdefault("knowledge_graph", {})["relationship_count"] = len(list((proof_kg.get("relationships") or [])))
        extractors.setdefault("knowledge_graph", {})["substantive_entity_count"] = len(list(combined_substantive_entity_ids))
        extractors.setdefault("knowledge_graph", {})["substantive_relationship_count"] = len(list(combined_substantive_relationship_ids))

    def _build_bm25_index(self, dataset_id: str, documents: Sequence[DocketDocument]) -> Dict[str, Any]:
        index_documents = [
            {
                "id": document.document_id,
                "text": document.text or document.title,
                "metadata": {
                    "docket_id": document.docket_id,
                    "title": document.title,
                    "date_filed": document.date_filed,
                    "document_number": document.document_number,
                },
            }
            for document in documents
            if (document.text or document.title).strip()
        ]
        bm25_index = build_bm25_index(index_documents)
        bm25_index["index_id"] = f"{dataset_id}_bm25"
        bm25_index.setdefault("stats", {})["document_count"] = int(bm25_index.get("document_count") or 0)
        return bm25_index

    def _build_vector_index(self, dataset_id: str, documents: Sequence[DocketDocument]) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        prepared_documents = [document for document in documents if (document.text or document.title).strip()]
        vectors, vector_metadata = embed_texts_with_router_or_local(
            [document.text or document.title for document in prepared_documents],
            fallback_dimension=self.vector_dimension,
        )
        for document, vector in zip(prepared_documents, vectors):
            items.append(
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "date_filed": document.date_filed,
                    "document_number": document.document_number,
                    "vector": vector,
                    "norm": self._vector_norm(vector),
                }
            )
        return {
            "index_id": f"{dataset_id}_vector",
            "dimension": self.vector_dimension,
            "metric": "cosine",
            "backend": str(vector_metadata.get("backend") or "local_hashed_term_projection"),
            "provider": str(vector_metadata.get("provider") or ""),
            "model_name": str(vector_metadata.get("model_name") or ""),
            "document_count": len(items),
            "items": items,
        }

    def _embed_text(self, text: str) -> List[float]:
        return hashed_term_projection(text, dimension=self.vector_dimension)

    def _vector_norm(self, vector: Iterable[float]) -> float:
        return math.sqrt(sum(float(value) * float(value) for value in vector))


def search_docket_dataset_bm25(
    dataset: DocketDatasetObject | Dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Search the in-memory BM25-style artifact for a docket dataset."""

    dataset_payload = dataset.to_dict() if isinstance(dataset, DocketDatasetObject) else dict(dataset)
    bm25_index = dict(dataset_payload.get("bm25_index") or {})
    documents = list(bm25_index.get("documents") or [])
    results = bm25_search_documents(query, documents, top_k=top_k)
    return {
        "query": query,
        "top_k": top_k,
        "results": results,
        "result_count": len(results),
        "source": "local_bm25",
    }


def search_docket_dataset_vector(
    dataset: DocketDatasetObject | Dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
    vector_dimension: int = 32,
) -> Dict[str, Any]:
    """Search the lightweight in-memory vector index for a docket dataset."""

    dataset_payload = dataset.to_dict() if isinstance(dataset, DocketDatasetObject) else dict(dataset)
    vector_index = dict(dataset_payload.get("vector_index") or {})
    items = list(vector_index.get("items") or [])
    builder = DocketDatasetBuilder(vector_dimension=vector_dimension)
    query_vector = embed_query_for_backend(
        query,
        backend=str(vector_index.get("backend") or "local_hashed_term_projection"),
        dimension=int(vector_index.get("dimension") or builder.vector_dimension),
        provider=str(vector_index.get("provider") or "") or None,
        model_name=str(vector_index.get("model_name") or "") or None,
    )
    scored: List[Dict[str, Any]] = []
    for item in items:
        vector = list(item.get("vector") or [])
        score = vector_dot(query_vector, vector)
        scored.append(
            {
                "document_id": item.get("document_id"),
                "title": item.get("title"),
                "date_filed": item.get("date_filed"),
                "document_number": item.get("document_number"),
                "score": score,
                "backend": "local_hashed_term_projection",
            }
        )
    scored.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    results = scored[:top_k]
    return {
        "query": query,
        "top_k": top_k,
        "results": results,
        "result_count": len(results),
    }


def build_docket_deontic_artifacts(
    *,
    dataset_id: str,
    docket_id: str,
    plaintiff_docket: Sequence[Dict[str, Any]],
    defendant_docket: Sequence[Dict[str, Any]],
    authorities: Sequence[Dict[str, Any]],
    explicit_statements: Optional[Sequence[Dict[str, Any]]] = None,
) -> tuple[DeonticGraph, Dict[str, Any]]:
    """Build a deontic graph and trigger state for docket party obligations."""

    inferred_statements: List[Dict[str, Any]] = list(explicit_statements or [])
    trigger_entries: List[Dict[str, Any]] = []
    authority_refs = [
        {
            "id": f"authority_{_safe_identifier(item.get('id') or item.get('title') or item.get('text') or index)}",
            "label": str(item.get("title") or item.get("label") or item.get("text") or f"Authority {index}"),
            "attributes": {"authority_type": item.get("authority_type"), "source_text": item.get("text")},
        }
        for index, item in enumerate(authorities, start=1)
        if isinstance(item, dict)
    ]

    for party, docket_items in (("plaintiff", plaintiff_docket), ("defendant", defendant_docket)):
        for index, item in enumerate(docket_items, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("description") or item.get("title") or "").strip()
            title = str(item.get("title") or item.get("label") or text or f"{party.title()} docket item {index}").strip()
            matched_keywords = _deontic_trigger_keywords(text or title)
            modality = _infer_docket_modality(text or title)
            action = _infer_docket_action(text or title)
            needs_analysis = bool(matched_keywords or authority_refs)
            trigger_id = f"{dataset_id}:trigger:{party}:{_safe_identifier(item.get('id') or title or index)}"
            trigger_entries.append(
                {
                    "trigger_id": trigger_id,
                    "party": party,
                    "source_type": "docket_item",
                    "source_id": str(item.get("id") or trigger_id),
                    "title": title,
                    "matched_keywords": matched_keywords,
                    "needs_analysis": needs_analysis,
                    "modality": modality,
                    "action": action,
                    "authority_count": len(authority_refs),
                    "last_updated": _utc_now_isoformat(),
                }
            )
            if needs_analysis:
                inferred_statements.append(
                    {
                        "id": f"{dataset_id}:statement:{party}:{_safe_identifier(item.get('id') or title or index)}",
                        "entity": party.title(),
                        "modality": modality,
                        "action": action,
                        "document_source": title,
                        "context": text or title,
                        "conditions": [f"Filed on docket {docket_id}"],
                        "confidence": 0.76 if matched_keywords else 0.62,
                        "authorities": list(authority_refs),
                        "attributes": {
                            "party": party,
                            "trigger_id": trigger_id,
                            "source_type": "docket_item",
                            "source_id": str(item.get("id") or trigger_id),
                        },
                    }
                )

    for index, authority in enumerate(authorities, start=1):
        if not isinstance(authority, dict):
            continue
        title = str(authority.get("title") or authority.get("label") or authority.get("text") or f"Authority {index}").strip()
        authority_text = str(authority.get("text") or title).strip()
        matched_keywords = _deontic_trigger_keywords(authority_text)
        modality = _infer_docket_modality(authority_text)
        action = _infer_docket_action(authority_text)
        trigger_id = f"{dataset_id}:trigger:authority:{_safe_identifier(authority.get('id') or title or index)}"
        target_parties = _infer_authority_parties(authority_text)
        trigger_entries.append(
            {
                "trigger_id": trigger_id,
                "party": "all",
                "source_type": "authority",
                "source_id": str(authority.get("id") or title or index),
                "title": title,
                "matched_keywords": matched_keywords,
                "needs_analysis": True,
                "modality": modality,
                "action": action,
                "authority_count": 1,
                "target_parties": list(target_parties),
                "last_updated": _utc_now_isoformat(),
            }
        )
        for party in target_parties:
            inferred_statements.append(
                {
                    "id": f"{dataset_id}:statement:authority:{party}:{_safe_identifier(authority.get('id') or title or index)}",
                    "entity": party.title(),
                    "modality": modality,
                    "action": action,
                    "document_source": title,
                    "context": authority_text,
                    "conditions": [f"Authority listed on docket {docket_id}"],
                    "confidence": 0.83 if matched_keywords else 0.67,
                    "authorities": [
                        {
                            "id": f"authority_{_safe_identifier(authority.get('id') or title or index)}",
                            "label": title,
                            "attributes": {
                                "authority_type": authority.get("authority_type"),
                                "source_text": authority_text,
                            },
                        }
                    ],
                    "attributes": {
                        "party": party,
                        "trigger_id": trigger_id,
                        "source_type": "authority",
                        "source_id": str(authority.get("id") or title or index),
                    },
                }
            )

    graph = DeonticGraphBuilder().build_from_statements(inferred_statements)
    party_analysis = _build_party_deontic_analysis(graph, trigger_entries)
    trigger_summary = {
        "entry_count": len(trigger_entries),
        "pending_analysis_count": sum(1 for item in trigger_entries if item.get("needs_analysis")),
        "parties_requiring_analysis": sorted(
            _parties_requiring_analysis(trigger_entries)
        ),
        "authority_trigger_count": sum(1 for item in trigger_entries if item.get("source_type") == "authority"),
        "analyzed_party_count": len(party_analysis),
        "rule_count_by_party": {
            party: int(analysis.get("rule_count") or 0)
            for party, analysis in sorted(party_analysis.items())
        },
    }
    return graph, {
        "summary": trigger_summary,
        "entries": trigger_entries,
        "party_analysis": party_analysis,
    }


def _deontic_trigger_keywords(text: str) -> List[str]:
    lowered = str(text or "").lower()
    keywords = []
    for token in (
        "must",
        "shall",
        "ordered",
        "deadline",
        "required",
        "obligation",
        "prohibited",
        "may",
        "response",
        "answer",
        "discovery",
        "motion",
        "notice",
    ):
        if token in lowered:
            keywords.append(token)
    return keywords


def _infer_docket_modality(text: str) -> str:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("shall not", "must not", "prohibited", "forbidden")):
        return "prohibition"
    if any(token in lowered for token in ("may", "permitted", "allowed")):
        return "permission"
    return "obligation"


def _infer_docket_action(text: str) -> str:
    lowered = str(text or "").strip()
    if not lowered:
        return "analyze docket obligation"
    for token, action in (
        ("answer", "file an answer or response"),
        ("response", "serve a response"),
        ("discovery", "comply with discovery obligations"),
        ("motion", "respond to motion practice"),
        ("notice", "review and comply with notice requirements"),
        ("deadline", "meet the docket deadline"),
        ("order", "comply with the court order"),
    ):
        if token in lowered.lower():
            return action
    return f"analyze obligations arising from {lowered[:80]}"


def _infer_authority_parties(text: str) -> List[str]:
    lowered = str(text or "").lower()
    parties: List[str] = []
    if "plaintiff" in lowered:
        parties.append("plaintiff")
    if "defendant" in lowered:
        parties.append("defendant")
    if parties:
        return parties
    if any(token in lowered for token in ("parties", "party", "all parties", "either party", "both parties")):
        return ["plaintiff", "defendant"]
    return ["plaintiff", "defendant"]


def _parties_requiring_analysis(trigger_entries: Sequence[Dict[str, Any]]) -> List[str]:
    parties: set[str] = set()
    for item in trigger_entries:
        if not item.get("needs_analysis"):
            continue
        party = str(item.get("party") or "").strip().lower()
        if party in {"plaintiff", "defendant"}:
            parties.add(party)
        for target_party in list(item.get("target_parties") or []):
            normalized_target = str(target_party or "").strip().lower()
            if normalized_target in {"plaintiff", "defendant"}:
                parties.add(normalized_target)
    return sorted(parties)


def _build_party_deontic_analysis(graph: DeonticGraph, trigger_entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    assessments = {item.rule_id: item for item in graph.assess_rules()}
    conflicts = graph.detect_conflicts(only_active=False)
    trigger_map = {str(item.get("trigger_id") or ""): item for item in trigger_entries if item.get("trigger_id")}
    analysis_by_party: Dict[str, Dict[str, Any]] = {}

    for rule in graph.rules.values():
        party = _infer_rule_party(graph, rule)
        if not party:
            continue
        analysis = analysis_by_party.setdefault(
            party,
            {
                "party": party,
                "rule_count": 0,
                "active_rule_count": 0,
                "modalities": {},
                "governed_actions": [],
                "pending_rule_ids": [],
                "trigger_ids": [],
                "trigger_titles": [],
                "authority_ids": [],
                "authority_labels": [],
                "source_gap_rule_ids": [],
                "conflicts": [],
            },
        )
        analysis["rule_count"] += 1
        if rule.active:
            analysis["active_rule_count"] += 1
        modality = rule.modality.value
        analysis["modalities"][modality] = int(analysis["modalities"].get(modality) or 0) + 1

        target = graph.get_node(rule.target_id)
        target_label = target.label if target else rule.predicate
        if target_label and target_label not in analysis["governed_actions"]:
            analysis["governed_actions"].append(target_label)

        assessment = assessments.get(rule.id)
        if assessment and assessment.missing_sources:
            analysis["pending_rule_ids"].append(rule.id)
            analysis["source_gap_rule_ids"].append(rule.id)

        trigger_id = str((rule.attributes or {}).get("trigger_id") or "")
        if trigger_id:
            if trigger_id not in analysis["trigger_ids"]:
                analysis["trigger_ids"].append(trigger_id)
            trigger_entry = trigger_map.get(trigger_id) or {}
            trigger_title = str(trigger_entry.get("title") or "")
            if trigger_title and trigger_title not in analysis["trigger_titles"]:
                analysis["trigger_titles"].append(trigger_title)

        for authority_id in rule.authority_ids:
            if authority_id not in analysis["authority_ids"]:
                analysis["authority_ids"].append(authority_id)
            authority_node = graph.get_node(authority_id)
            authority_label = authority_node.label if authority_node else authority_id
            if authority_label and authority_label not in analysis["authority_labels"]:
                analysis["authority_labels"].append(authority_label)

    for conflict in conflicts:
        left_rule = graph.rules.get(conflict.rule_id)
        right_rule = graph.rules.get(conflict.conflicting_rule_id)
        parties = {
            _infer_rule_party(graph, rule)
            for rule in (left_rule, right_rule)
            if rule is not None
        }
        for party in sorted(value for value in parties if value):
            analysis = analysis_by_party.setdefault(
                party,
                {
                    "party": party,
                    "rule_count": 0,
                    "active_rule_count": 0,
                    "modalities": {},
                    "governed_actions": [],
                    "pending_rule_ids": [],
                    "trigger_ids": [],
                    "trigger_titles": [],
                    "authority_ids": [],
                    "authority_labels": [],
                    "source_gap_rule_ids": [],
                    "conflicts": [],
                },
            )
            analysis["conflicts"].append(conflict.to_dict())

    for party, analysis in analysis_by_party.items():
        analysis["pending_rule_count"] = len(analysis["pending_rule_ids"])
        analysis["source_gap_count"] = len(analysis["source_gap_rule_ids"])
        analysis["conflict_count"] = len(analysis["conflicts"])
        analysis["last_updated"] = _utc_now_isoformat()
        analysis["obligations"] = _governed_actions_for_modality(graph, party, "obligation")
        analysis["prohibitions"] = _governed_actions_for_modality(graph, party, "prohibition")
        analysis["permissions"] = _governed_actions_for_modality(graph, party, "permission")
        analysis["entitlements"] = _governed_actions_for_modality(graph, party, "entitlement")
    return analysis_by_party


def _infer_rule_party(graph: DeonticGraph, rule: Any) -> str:
    attributes = dict(getattr(rule, "attributes", {}) or {})
    explicit_party = str(attributes.get("party") or "").strip().lower()
    if explicit_party in {"plaintiff", "defendant"}:
        return explicit_party
    for source_id in list(getattr(rule, "source_ids", []) or []):
        node = graph.get_node(source_id)
        label = str(node.label if node else "").strip().lower()
        if label in {"plaintiff", "defendant"}:
            return label
    return ""


def _governed_actions_for_modality(graph: DeonticGraph, party: str, modality: str) -> List[str]:
    actions: List[str] = []
    for rule in graph.rules.values():
        if rule.modality.value != modality:
            continue
        if _infer_rule_party(graph, rule) != party:
            continue
        target = graph.get_node(rule.target_id)
        label = target.label if target else rule.predicate
        if label and label not in actions:
            actions.append(label)
    return actions


def summarize_docket_dataset(dataset: DocketDatasetObject | Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact manifest-style summary for a docket dataset."""

    dataset_object = dataset if isinstance(dataset, DocketDatasetObject) else DocketDatasetObject.from_dict(dict(dataset))
    document_dates = [document.date_filed for document in dataset_object.documents if document.date_filed]
    document_numbers = [document.document_number for document in dataset_object.documents if document.document_number]
    return {
        **dataset_object.summary(),
        "date_range": {
            "min": min(document_dates) if document_dates else "",
            "max": max(document_dates) if document_dates else "",
        },
        "document_numbers_present": len(document_numbers),
        "documents_with_text": sum(1 for document in dataset_object.documents if document.text.strip()),
        "documents_with_source_url": sum(1 for document in dataset_object.documents if document.source_url.strip()),
        "plaintiff_docket_count": len(dataset_object.plaintiff_docket),
        "defendant_docket_count": len(dataset_object.defendant_docket),
        "authority_count": len(dataset_object.authorities),
        "deontic_rule_count": len(list((dataset_object.deontic_graph or {}).get("rules") or [])),
        "deontic_trigger_count": len(list((dataset_object.deontic_triggers or {}).get("entries") or [])),
        "proof_assistant_work_item_count": len(list((dataset_object.proof_assistant or {}).get("agenda") or [])),
        "proof_assistant_formula_count": len(
            list(((dataset_object.proof_assistant or {}).get("temporal_fol") or {}).get("formulas") or [])
        ),
        "proof_tactician_plan_count": len(list(((dataset_object.proof_assistant or {}).get("tactician") or {}).get("plans") or [])),
        "parties_requiring_deontic_analysis": list(
            (((dataset_object.deontic_triggers or {}).get("summary") or {}).get("parties_requiring_analysis") or [])
        ),
    }


__all__ = [
    "DocketDatasetBuilder",
    "DocketDatasetObject",
    "DocketDocument",
    "build_docket_deontic_artifacts",
    "build_docket_proof_assistant",
    "search_docket_dataset_bm25",
    "search_docket_dataset_vector",
    "summarize_docket_dataset",
]
