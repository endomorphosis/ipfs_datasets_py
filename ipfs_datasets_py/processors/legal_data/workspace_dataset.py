"""Workspace dataset import and indexing helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..protocol import Entity, KnowledgeGraph, Relationship
from .document_structure import parse_legal_document_to_graph
from .docket_dataset import (
    DocketDatasetBuilder,
    _document_index_priority,
    _document_index_text,
    _document_index_title,
    _document_text_source,
    _document_retrieval_evidence_quality,
    _safe_identifier,
    _utc_now_isoformat,
)
from ..retrieval import bm25_search_documents, embed_query_for_backend, vector_dot


@dataclass
class WorkspaceDocument:
    """Normalized workspace evidence record."""

    document_id: str
    workspace_id: str
    title: str
    text: str
    captured_at: str = ""
    document_number: str = ""
    source_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def docket_id(self) -> str:
        return self.workspace_id

    @property
    def date_filed(self) -> str:
        return self.captured_at

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkspaceDatasetObject:
    """Portable workspace dataset object with deferred retrieval artifacts."""

    dataset_id: str
    workspace_id: str
    workspace_name: str
    source_type: str
    documents: List[WorkspaceDocument] = field(default_factory=list)
    collections: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_graph: Dict[str, Any] = field(default_factory=dict)
    bm25_index: Dict[str, Any] = field(default_factory=dict)
    vector_index: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "source_type": self.source_type,
            "documents": [document.to_dict() for document in self.documents],
            "collections": [dict(item) for item in self.collections],
            "knowledge_graph": dict(self.knowledge_graph),
            "bm25_index": dict(self.bm25_index),
            "vector_index": dict(self.vector_index),
            "metadata": dict(self.metadata),
        }

    def summary(self) -> Dict[str, Any]:
        return summarize_workspace_dataset(self)

    def write_json(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return output_path

    def write_single_parquet(self, path: str | Path) -> Dict[str, Any]:
        return export_workspace_dataset_single_parquet(self, path)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceDatasetObject":
        return cls(
            dataset_id=str(data.get("dataset_id") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
            workspace_name=str(data.get("workspace_name") or ""),
            source_type=str(data.get("source_type") or "workspace"),
            documents=[
                WorkspaceDocument(
                    document_id=str(item.get("document_id") or ""),
                    workspace_id=str(item.get("workspace_id") or data.get("workspace_id") or ""),
                    title=str(item.get("title") or ""),
                    text=str(item.get("text") or ""),
                    captured_at=str(item.get("captured_at") or item.get("date_filed") or ""),
                    document_number=str(item.get("document_number") or ""),
                    source_url=str(item.get("source_url") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in list(data.get("documents") or [])
                if isinstance(item, dict)
            ],
            collections=[dict(item) for item in list(data.get("collections") or []) if isinstance(item, dict)],
            knowledge_graph=dict(data.get("knowledge_graph") or {}),
            bm25_index=dict(data.get("bm25_index") or {}),
            vector_index=dict(data.get("vector_index") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "WorkspaceDatasetObject":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class WorkspaceDatasetBuilder(DocketDatasetBuilder):
    """Import a workspace corpus and build deferred retrieval artifacts."""

    def build_from_workspace(
        self,
        workspace: Dict[str, Any],
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
    ) -> WorkspaceDatasetObject:
        normalized_documents = self._normalize_workspace_documents(workspace)
        workspace_id = str(workspace.get("workspace_id") or workspace.get("id") or workspace.get("dataset_id") or "workspace")
        workspace_name = str(workspace.get("workspace_name") or workspace.get("title") or workspace_id)
        source_type = str(workspace.get("source_type") or workspace.get("workspace_type") or "workspace")
        dataset_id = f"workspace_dataset_{_safe_identifier(workspace_id)}"
        collections = self._normalize_workspace_collections(workspace.get("collections") or workspace.get("sources") or [])
        index_documents = self._select_index_documents(normalized_documents)

        knowledge_graph = self._build_knowledge_graph(dataset_id, workspace_id, workspace_name, source_type, index_documents) if include_knowledge_graph else {}
        bm25_index = self._build_bm25_index(dataset_id, index_documents) if include_bm25 else {}
        vector_index = self._build_vector_index(dataset_id, index_documents) if include_vector_index else {}
        artifact_provenance = {
            "knowledge_graph": {"backend": "parsed_document_structure_graph", "is_mock": False},
            "bm25_index": {"backend": "local_bm25", "is_mock": False},
            "vector_index": {
                "backend": str(vector_index.get("backend") or "local_hashed_term_projection"),
                "provider": str(vector_index.get("provider") or ""),
                "model_name": str(vector_index.get("model_name") or ""),
                "is_mock": False,
            },
            "retrieval_index": {
                "selected_document_count": len(index_documents),
                "excluded_document_count": max(0, len(normalized_documents) - len(index_documents)),
            },
        }
        artifact_status = {
            "knowledge_graph": bool(knowledge_graph),
            "bm25_index": bool(bm25_index),
            "vector_index": bool(vector_index),
            "retrieval_index": bool(index_documents),
        }

        return WorkspaceDatasetObject(
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            source_type=source_type,
            documents=normalized_documents,
            collections=collections,
            knowledge_graph=knowledge_graph,
            bm25_index=bm25_index,
            vector_index=vector_index,
            metadata={
                "imported_at": _utc_now_isoformat(),
                "document_count": len(normalized_documents),
                "collection_count": len(collections),
                "artifact_provenance": artifact_provenance,
                "artifact_status": artifact_status,
                "source_type": source_type,
                "source_path": str(workspace.get("source_path") or ""),
            },
        )

    def build_from_json_file(
        self,
        path: str | Path,
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
    ) -> WorkspaceDatasetObject:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Workspace JSON payload must be an object")
        payload.setdefault("source_type", "json_file")
        payload.setdefault("source_path", str(Path(path)))
        return self.build_from_workspace(
            payload,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )

    def build_from_google_voice_manifest(
        self,
        manifest: Dict[str, Any] | str | Path,
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
    ) -> WorkspaceDatasetObject:
        payload = (
            json.loads(Path(manifest).read_text(encoding="utf-8"))
            if isinstance(manifest, (str, Path))
            else dict(manifest)
        )
        bundles = [dict(item) for item in list(payload.get("bundles") or []) if isinstance(item, dict)]
        workspace_id = str(payload.get("workspace_id") or payload.get("manifest_id") or payload.get("source_kind") or "google_voice")

        def _read_text_file(path_value: Any) -> str:
            path_text = str(path_value or "").strip()
            if not path_text:
                return ""
            try:
                return Path(path_text).read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                return ""

        def _read_json_file(path_value: Any) -> Dict[str, Any]:
            path_text = str(path_value or "").strip()
            if not path_text:
                return {}
            try:
                parsed = json.loads(Path(path_text).read_text(encoding="utf-8"))
            except Exception:
                return {}
            return dict(parsed) if isinstance(parsed, dict) else {}

        def _read_attachment_text(attachment: Dict[str, Any]) -> str:
            path_text = str(attachment.get("path") or "").strip()
            if not path_text:
                return ""
            attachment_path = Path(path_text)
            suffix = attachment_path.suffix.lower()
            content_type = str(attachment.get("content_type") or "").strip().lower()
            text_like_suffixes = {".txt", ".md", ".json", ".csv", ".html", ".htm", ".xml", ".eml"}
            if suffix not in text_like_suffixes and not content_type.startswith("text/"):
                return ""
            try:
                return attachment_path.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                return ""

        collections: List[Dict[str, Any]] = [
            {
                "id": str(payload.get("source_kind") or "google_voice"),
                "title": str(payload.get("source_kind") or "google_voice").replace("_", " ").title(),
                "source_path": str(payload.get("manifest_path") or payload.get("source") or ""),
                "source_type": "google_voice",
            }
        ]
        documents: List[Dict[str, Any]] = []
        for index, bundle in enumerate(bundles, start=1):
            event_payload = _read_json_file(bundle.get("event_json_path") or bundle.get("parsed_path"))
            transcript_text = _read_text_file(bundle.get("transcript_path"))
            text = str(bundle.get("text_content") or transcript_text or event_payload.get("text_content") or "")
            participants = list(bundle.get("participants") or bundle.get("phone_numbers") or event_payload.get("participants") or event_payload.get("phone_numbers") or [])
            phone_numbers = list(bundle.get("phone_numbers") or event_payload.get("phone_numbers") or participants)
            attachments = list(bundle.get("attachments") or event_payload.get("attachments") or [])
            enrichments = list(bundle.get("enrichments") or event_payload.get("enrichments") or [])
            parent_document_id = str(bundle.get("event_id") or event_payload.get("event_id") or f"voice_{index}")
            parent_title = str(
                bundle.get("evidence_title")
                or bundle.get("title")
                or event_payload.get("title")
                or bundle.get("event_type")
                or event_payload.get("event_type")
                or f"Google Voice event {index}"
            )
            captured_at = str(bundle.get("timestamp") or bundle.get("date") or event_payload.get("timestamp") or event_payload.get("date") or "")
            bundle_collection_id = f"google_voice_bundle_{_safe_identifier(parent_document_id)}"
            attachment_document_ids: List[str] = []
            enrichment_document_ids: List[str] = []
            attachment_documents: List[Dict[str, Any]] = []
            enrichment_documents: List[Dict[str, Any]] = []

            for attachment_index, attachment in enumerate(attachments, start=1):
                if not isinstance(attachment, dict):
                    continue
                attachment_text = _read_attachment_text(attachment)
                if not attachment_text:
                    continue
                attachment_name = str(attachment.get("filename") or Path(str(attachment.get("path") or "attachment")).name or f"Attachment {attachment_index}")
                attachment_document_id = f"{parent_document_id}_attachment_{attachment_index}"
                attachment_document_ids.append(attachment_document_id)
                attachment_documents.append(
                    {
                        "id": attachment_document_id,
                        "title": f"{parent_title} - Attachment: {attachment_name}",
                        "text": attachment_text,
                        "timestamp": captured_at,
                        "source_url": str(attachment.get("path") or ""),
                        "document_type": "google_voice_attachment",
                        "metadata": {
                            "raw": dict(attachment),
                            "collection_id": bundle_collection_id,
                            "bundle_dir": str(bundle.get("bundle_dir") or event_payload.get("bundle_dir") or ""),
                            "parent_document_id": parent_document_id,
                            "participants": participants,
                            "phone_numbers": phone_numbers,
                            "attachment_kind": str(attachment.get("kind") or "attachment"),
                            "content_type": str(attachment.get("content_type") or ""),
                            "source_kind": bundle.get("source_kind") or event_payload.get("source_kind") or payload.get("source_kind"),
                        },
                    }
                )

            for enrichment_index, enrichment in enumerate(enrichments, start=1):
                if not isinstance(enrichment, dict):
                    continue
                enrichment_text = _read_text_file(enrichment.get("path"))
                if not enrichment_text:
                    continue
                enrichment_kind = str(enrichment.get("kind") or "enrichment")
                enrichment_label = enrichment_kind.replace("_", " ").title()
                enrichment_document_id = f"{parent_document_id}_enrichment_{enrichment_index}"
                enrichment_document_ids.append(enrichment_document_id)
                enrichment_documents.append(
                    {
                        "id": enrichment_document_id,
                        "title": f"{parent_title} - {enrichment_label}",
                        "text": enrichment_text,
                        "timestamp": captured_at,
                        "source_url": str(enrichment.get("path") or ""),
                        "document_type": "google_voice_enrichment",
                        "metadata": {
                            "raw": dict(enrichment),
                            "collection_id": bundle_collection_id,
                            "bundle_dir": str(bundle.get("bundle_dir") or event_payload.get("bundle_dir") or ""),
                            "parent_document_id": parent_document_id,
                            "participants": participants,
                            "phone_numbers": phone_numbers,
                            "enrichment_kind": enrichment_kind,
                            "source_attachment": str(enrichment.get("source_attachment") or ""),
                            "source_kind": bundle.get("source_kind") or event_payload.get("source_kind") or payload.get("source_kind"),
                        },
                    }
                )

            documents.append(
                {
                    "id": parent_document_id,
                    "title": parent_title,
                    "text": text,
                    "timestamp": captured_at,
                    "source_url": bundle.get("bundle_dir")
                    or bundle.get("event_json_path")
                    or bundle.get("parsed_path")
                    or bundle.get("transcript_path")
                    or "",
                    "document_type": bundle.get("event_type") or event_payload.get("event_type") or "google_voice_event",
                    "metadata": {
                        "raw": dict(bundle),
                        "collection_id": bundle_collection_id,
                        "bundle_dir": str(bundle.get("bundle_dir") or event_payload.get("bundle_dir") or ""),
                        "parsed": event_payload,
                        "participants": participants,
                        "phone_numbers": phone_numbers,
                        "attachment_document_ids": list(attachment_document_ids),
                        "attachment_paths": list(bundle.get("attachment_paths") or [str(item.get("path") or "") for item in attachments if isinstance(item, dict) and item.get("path")]),
                        "attachments": attachments,
                        "enrichment_document_ids": list(enrichment_document_ids),
                        "enrichment_paths": list(bundle.get("enrichment_paths") or [str(item.get("path") or "") for item in enrichments if isinstance(item, dict) and item.get("path")]),
                        "enrichments": enrichments,
                        "transcript_path": str(bundle.get("transcript_path") or event_payload.get("transcript_path") or ""),
                        "source_html_path": str(bundle.get("source_html_path") or event_payload.get("source_html_path") or ""),
                        "deduped_gmail_message_ids": list(bundle.get("deduped_gmail_message_ids") or event_payload.get("deduped_gmail_message_ids") or []),
                        "source_kind": bundle.get("source_kind") or event_payload.get("source_kind") or payload.get("source_kind"),
                    },
                }
            )
            documents.extend(attachment_documents)
            documents.extend(enrichment_documents)
            collections.append(
                {
                    "id": bundle_collection_id,
                    "title": parent_title,
                    "source_path": str(bundle.get("bundle_dir") or event_payload.get("bundle_dir") or ""),
                    "source_type": "google_voice_bundle",
                    "parent_document_id": parent_document_id,
                    "event_type": bundle.get("event_type") or event_payload.get("event_type") or "google_voice_event",
                    "timestamp": captured_at,
                    "participants": participants,
                    "phone_numbers": phone_numbers,
                    "document_ids": [parent_document_id, *attachment_document_ids, *enrichment_document_ids],
                }
            )

        workspace = {
            "workspace_id": workspace_id,
            "workspace_name": str(payload.get("workspace_name") or payload.get("source_kind") or "Google Voice Workspace"),
            "source_type": "google_voice",
            "source_path": str(payload.get("manifest_path") or payload.get("source") or ""),
            "collections": collections,
            "documents": documents,
        }
        return self.build_from_workspace(
            workspace,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )

    def build_from_discord_export(
        self,
        export_payload: Dict[str, Any] | str | Path,
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
    ) -> WorkspaceDatasetObject:
        payload = (
            json.loads(Path(export_payload).read_text(encoding="utf-8"))
            if isinstance(export_payload, (str, Path))
            else dict(export_payload)
        )
        messages = [dict(item) for item in list(payload.get("messages") or []) if isinstance(item, dict)]
        channel_id = str(payload.get("channel_id") or payload.get("id") or "discord_channel")
        channel_name = str(payload.get("channel_name") or payload.get("name") or channel_id)
        guild_id = str(payload.get("guild_id") or "")
        guild_name = str(payload.get("guild_name") or guild_id or "")
        workspace = {
            "workspace_id": channel_id,
            "workspace_name": channel_name,
            "source_type": "discord",
            "collections": [
                {
                    "id": channel_id,
                    "title": channel_name,
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "source_type": "discord",
                }
            ],
            "documents": [
                {
                    "id": message.get("id") or f"discord_message_{index}",
                    "title": str(message.get("author") or message.get("username") or "Discord message"),
                    "text": str(message.get("content") or message.get("text") or ""),
                    "timestamp": message.get("timestamp") or "",
                    "source_url": str(payload.get("export_path") or ""),
                    "document_type": "discord_message",
                    "thread_id": message.get("thread_id") or channel_id,
                    "metadata": {
                        "raw": dict(message),
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "guild_id": guild_id,
                        "guild_name": guild_name,
                        "attachments": list(message.get("attachments") or []),
                        "embeds": list(message.get("embeds") or []),
                        "reactions": list(message.get("reactions") or []),
                    },
                }
                for index, message in enumerate(messages, start=1)
            ],
        }
        return self.build_from_workspace(
            workspace,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )

    def build_from_email_export(
        self,
        export_payload: Dict[str, Any] | str | Path,
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
    ) -> WorkspaceDatasetObject:
        payload = (
            json.loads(Path(export_payload).read_text(encoding="utf-8"))
            if isinstance(export_payload, (str, Path))
            else dict(export_payload)
        )
        emails = [dict(item) for item in list(payload.get("emails") or []) if isinstance(item, dict)]
        folder = str(payload.get("folder") or payload.get("mailbox") or payload.get("label") or "email_export")

        def _extract_email_text(email: Dict[str, Any]) -> tuple[str, Dict[str, Any] | None]:
            text = str(
                email.get("body_text")
                or email.get("body_html")
                or email.get("snippet")
                or email.get("plain_text")
                or ""
            ).strip()
            if text:
                return text, None
            parsed_path = email.get("parsed_path") or email.get("parsed_json_path") or ""
            if parsed_path:
                try:
                    parsed_payload = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
                except Exception:
                    parsed_payload = None
                if isinstance(parsed_payload, dict):
                    parsed_text = str(
                        parsed_payload.get("body_text")
                        or parsed_payload.get("body_html")
                        or parsed_payload.get("snippet")
                        or parsed_payload.get("plain_text")
                        or parsed_payload.get("content")
                        or ""
                    ).strip()
                    if parsed_text:
                        return parsed_text, parsed_payload
            return "", None

        workspace = {
            "workspace_id": _safe_identifier(folder),
            "workspace_name": folder,
            "source_type": "email",
            "collections": [
                {
                    "id": _safe_identifier(folder),
                    "title": folder,
                    "protocol": payload.get("protocol"),
                    "server": payload.get("server"),
                    "source_type": "email",
                }
            ],
            "documents": [
                {
                    "id": email.get("message_id_header") or email.get("message_id") or f"email_{index}",
                    "title": (email.get("subject") or (parsed or {}).get("subject") or f"Email {index}"),
                    "text": text,
                    "timestamp": email.get("date") or email.get("sent_at") or (parsed or {}).get("date") or "",
                    "message_id": email.get("message_id_header")
                    or email.get("message_id")
                    or (parsed or {}).get("message_id")
                    or "",
                    "source_url": str(payload.get("output_path") or ""),
                    "document_type": "email_message",
                    "metadata": {
                        "raw": dict(email),
                        "parsed": parsed or {},
                        "from": email.get("from"),
                        "to": email.get("to"),
                        "cc": email.get("cc"),
                        "bcc": email.get("bcc"),
                        "attachments": list(email.get("attachments") or []),
                        "folder": folder,
                        "protocol": payload.get("protocol"),
                        "server": payload.get("server"),
                    },
                }
                for index, email in enumerate(emails, start=1)
                for text, parsed in [(_extract_email_text(email))]
            ],
        }
        return self.build_from_workspace(
            workspace,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )

    def build_from_imap_snippet_summary(
        self,
        summary_payload: Dict[str, Any] | str | Path,
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
    ) -> WorkspaceDatasetObject:
        payload = (
            json.loads(Path(summary_payload).read_text(encoding="utf-8"))
            if isinstance(summary_payload, (str, Path))
            else summary_payload
        )
        if not isinstance(payload, list):
            raise ValueError("IMAP snippet summary payload must be a list")
        summary_path = Path(summary_payload) if isinstance(summary_payload, (str, Path)) else None
        workspace_id = _safe_identifier(str(summary_path.parent.name if summary_path else "imap_snippets"))
        workspace = {
            "workspace_id": workspace_id,
            "workspace_name": str(summary_path.parent.name if summary_path else "IMAP Snippets"),
            "source_type": "imap_snippets",
            "collections": [
                {
                    "id": workspace_id,
                    "title": str(summary_path.parent.name if summary_path else "IMAP Snippets"),
                    "source_path": str(summary_path or ""),
                    "source_type": "imap_snippets",
                }
            ],
            "documents": [],
        }
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            body_path = str(item.get("body_path") or "")
            headers_path = str(item.get("headers_path") or "")
            body_text = ""
            header_text = ""
            if body_path:
                try:
                    body_text = Path(body_path).read_text(encoding="utf-8", errors="ignore").strip()
                except Exception:
                    body_text = ""
            if headers_path:
                try:
                    header_text = Path(headers_path).read_text(encoding="utf-8", errors="ignore").strip()
                except Exception:
                    header_text = ""
            text = body_text or header_text
            workspace["documents"].append(
                {
                    "id": f"imap_snippet_{index}",
                    "title": f"IMAP snippet {index}",
                    "text": text,
                    "timestamp": "",
                    "source_url": body_path or headers_path,
                    "document_type": "imap_snippet",
                    "metadata": {
                        "raw": dict(item),
                        "body_path": body_path,
                        "headers_path": headers_path,
                        "headers_text": header_text,
                    },
                }
            )
        return self.build_from_workspace(
            workspace,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )

    def build_from_directory(
        self,
        directory: str | Path,
        *,
        workspace_id: Optional[str] = None,
        workspace_name: Optional[str] = None,
        source_type: str = "directory",
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
        glob_pattern: str = "*",
    ) -> WorkspaceDatasetObject:
        root = Path(directory)
        if not root.exists():
            raise FileNotFoundError(f"Workspace directory not found: {root}")
        if not root.is_dir():
            raise ValueError(f"Workspace import path is not a directory: {root}")

        documents: List[Dict[str, Any]] = []
        supported_suffixes = {".txt", ".md", ".json", ".eml"}
        for path in sorted(candidate for candidate in root.rglob(glob_pattern) if candidate.is_file()):
            if path.suffix.lower() not in supported_suffixes:
                continue
            if path.suffix.lower() == ".json":
                try:
                    json_payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    json_payload = None
                if isinstance(json_payload, dict):
                    text = str(
                        json_payload.get("text")
                        or json_payload.get("plain_text")
                        or json_payload.get("content")
                        or json_payload.get("body")
                        or json_payload.get("message")
                        or json_payload.get("description")
                        or ""
                    ).strip()
                    if text:
                        documents.append(
                            {
                                "id": json_payload.get("id") or path.stem,
                                "title": json_payload.get("title") or json_payload.get("subject") or path.stem,
                                "text": text,
                                "source_url": str(path),
                                "document_type": json_payload.get("document_type") or "json",
                                "metadata": {"raw": json_payload},
                            }
                        )
                continue
            if path.suffix.lower() == ".eml":
                try:
                    from email import policy
                    from email.parser import BytesParser

                    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
                    body = message.get_body(preferencelist=("plain", "html"))
                    text = body.get_content().strip() if body else ""
                except Exception:
                    text = ""
                    message = None
                if not text:
                    continue
                subject = str(message.get("subject") or path.stem) if message else path.stem
                documents.append(
                    {
                        "id": path.stem,
                        "title": subject,
                        "text": text,
                        "source_url": str(path),
                        "document_type": "eml",
                        "source_path": str(path),
                        "metadata": {
                            "from": str(message.get("from") or "") if message else "",
                            "to": str(message.get("to") or "") if message else "",
                            "date": str(message.get("date") or "") if message else "",
                        },
                    }
                )
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

        workspace_payload = {
            "workspace_id": workspace_id or root.name,
            "workspace_name": workspace_name or root.name.replace("_", " ").replace("-", " "),
            "source_type": source_type,
            "source_path": str(root),
            "documents": documents,
            "collections": [
                {
                    "id": _safe_identifier(root.name),
                    "title": workspace_name or root.name,
                    "source_path": str(root),
                    "source_type": source_type,
                }
            ],
        }
        return self.build_from_workspace(
            workspace_payload,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )

    def build_from_pdf_paths(
        self,
        pdf_paths: Sequence[str | Path],
        *,
        workspace_id: Optional[str] = None,
        workspace_name: Optional[str] = None,
        source_type: str = "pdf_directory",
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
        include_formal_logic: bool = True,
        formal_logic_max_documents: Optional[int] = None,
        max_pdf_pages: Optional[int] = None,
        max_pdf_chars: Optional[int] = None,
    ) -> WorkspaceDatasetObject:
        """Build a workspace dataset from local PDF files."""

        resolved_paths = [Path(path).expanduser().resolve() for path in pdf_paths]
        documents: List[Dict[str, Any]] = []
        collections: List[Dict[str, Any]] = []
        extraction_errors: List[Dict[str, Any]] = []

        for index, path in enumerate(sorted(resolved_paths, key=lambda item: str(item)), start=1):
            if not path.exists() or not path.is_file() or path.suffix.lower() != ".pdf":
                continue
            extraction = _extract_pdf_text(path, max_pages=max_pdf_pages)
            text = str(extraction.get("text") or "").strip()
            if max_pdf_chars is not None and int(max_pdf_chars) > 0:
                text = text[: int(max_pdf_chars)]
            if not text:
                extraction_errors.append(
                    {
                        "path": str(path),
                        "error": str(extraction.get("error") or "no_text_extracted"),
                        "page_count": int(extraction.get("page_count") or 0),
                    }
                )
                continue

            collection_id = _safe_identifier(path.parent.name or "pdfs")
            document_id = _safe_identifier(f"{path.parent.name}-{path.stem}-{index}") or f"pdf_{index}"
            documents.append(
                {
                    "id": document_id,
                    "title": path.stem.replace("_", " ").replace("-", " ").strip() or path.name,
                    "text": text,
                    "source_url": str(path),
                    "document_type": "pdf",
                    "page_count": int(extraction.get("page_count") or 0),
                    "metadata": {
                        "collection_id": collection_id,
                        "document_type": "pdf",
                        "source_path": str(path),
                        "source_name": path.name,
                        "source_suffix": path.suffix.lower(),
                        "parent_directory": str(path.parent),
                        "relative_parent": path.parent.name,
                        "file_size_bytes": path.stat().st_size,
                        "text_extraction": {
                            "source": str(extraction.get("backend") or "pypdf"),
                            "backend": str(extraction.get("backend") or "pypdf"),
                            "page_count": int(extraction.get("page_count") or 0),
                            "character_count": len(text),
                            "truncated": bool(max_pdf_chars is not None and int(max_pdf_chars) > 0 and len(str(extraction.get("text") or "")) > len(text)),
                        },
                    },
                }
            )
            if not any(str(item.get("id") or "") == collection_id for item in collections):
                collections.append(
                    {
                        "id": collection_id,
                        "title": path.parent.name.replace("_", " ").replace("-", " ") or "PDFs",
                        "source_path": str(path.parent),
                        "source_type": source_type,
                        "document_type": "pdf",
                    }
                )

        workspace = {
            "workspace_id": workspace_id or _safe_identifier(workspace_name or source_type or "pdf_workspace"),
            "workspace_name": workspace_name or "PDF Workspace Dataset",
            "source_type": source_type,
            "source_path": os.path.commonpath([str(path.parent) for path in resolved_paths]) if resolved_paths else "",
            "collections": collections,
            "documents": documents,
        }
        dataset = self.build_from_workspace(
            workspace,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
        )
        metadata = dict(dataset.metadata or {})
        metadata["pdf_ingest"] = {
            "input_pdf_count": len(resolved_paths),
            "ingested_document_count": len(documents),
            "extraction_error_count": len(extraction_errors),
            "extraction_errors": extraction_errors[:25],
            "max_pdf_pages": max_pdf_pages,
            "max_pdf_chars": max_pdf_chars,
        }
        if include_formal_logic and documents:
            formal_logic = _build_workspace_formal_logic_metadata(
                dataset,
                max_documents=formal_logic_max_documents,
            )
            metadata["formal_logic"] = formal_logic
            metadata["formal_logic_summary"] = dict(formal_logic.get("summary") or {})
            artifact_status = dict(metadata.get("artifact_status") or {})
            artifact_status["formal_logic"] = bool(formal_logic.get("summary"))
            metadata["artifact_status"] = artifact_status
            artifact_provenance = dict(metadata.get("artifact_provenance") or {})
            artifact_provenance["formal_logic"] = {
                "backend": "repo_native_formal_logic_pipeline",
                "is_mock": False,
                "max_documents": formal_logic_max_documents,
            }
            metadata["artifact_provenance"] = artifact_provenance
            formal_graph = dict(formal_logic.get("knowledge_graph") or {})
            if formal_graph:
                dataset.knowledge_graph = _merge_workspace_knowledge_graphs(dataset.knowledge_graph, formal_graph)
        dataset.metadata = metadata
        return dataset

    def build_from_pdf_directory(
        self,
        directory: str | Path,
        *,
        workspace_id: Optional[str] = None,
        workspace_name: Optional[str] = None,
        source_type: str = "pdf_directory",
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
        include_formal_logic: bool = True,
        formal_logic_max_documents: Optional[int] = None,
        max_pdf_pages: Optional[int] = None,
        max_pdf_chars: Optional[int] = None,
        glob_pattern: str = "*.pdf",
        exclude_dirs: Optional[Sequence[str]] = None,
    ) -> WorkspaceDatasetObject:
        root = Path(directory).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"PDF workspace directory not found: {root}")
        if not root.is_dir():
            raise ValueError(f"PDF workspace import path is not a directory: {root}")
        excluded = {str(item).strip() for item in list(exclude_dirs or []) if str(item).strip()}
        paths = [
            path
            for path in root.rglob(glob_pattern or "*.pdf")
            if path.is_file()
            and path.suffix.lower() == ".pdf"
            and not any(part in excluded for part in path.relative_to(root).parts)
        ]
        return self.build_from_pdf_paths(
            paths,
            workspace_id=workspace_id or _safe_identifier(root.name),
            workspace_name=workspace_name or root.name.replace("_", " ").replace("-", " "),
            source_type=source_type,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
            include_formal_logic=include_formal_logic,
            formal_logic_max_documents=formal_logic_max_documents,
            max_pdf_pages=max_pdf_pages,
            max_pdf_chars=max_pdf_chars,
        )

    def preview_retrieval_index(
        self,
        workspace: Dict[str, Any],
        *,
        min_evidence_quality: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_documents = self._normalize_workspace_documents(workspace)
        index_documents = self._select_index_documents(normalized_documents)
        evidence_counts: Dict[str, int] = {}
        for document in index_documents:
            evidence_quality = str((document.metadata.get("retrieval_index") or {}).get("evidence_quality") or "metadata")
            evidence_counts[evidence_quality] = evidence_counts.get(evidence_quality, 0) + 1
        if min_evidence_quality is not None:
            threshold_map = {"metadata": 0, "rendered": 1, "plain_text": 2, "extracted_pdf": 3}
            threshold = threshold_map.get(str(min_evidence_quality).strip().lower())
            if threshold is None:
                raise ValueError("min_evidence_quality must be one of: metadata, rendered, plain_text, extracted_pdf")
            index_documents = [
                document
                for document in index_documents
                if threshold_map.get(
                    str((document.metadata.get("retrieval_index") or {}).get("evidence_quality") or "metadata"),
                    0,
                ) >= threshold
            ]
        return {
            "workspace_id": str(workspace.get("workspace_id") or workspace.get("id") or "workspace"),
            "document_count": len(normalized_documents),
            "selected_document_count": len(index_documents),
            "excluded_document_count": max(0, len(normalized_documents) - len(index_documents)),
            "evidence_quality_counts": evidence_counts,
            "min_evidence_quality": min_evidence_quality,
            "documents": [document.to_dict() for document in index_documents],
        }

    def _normalize_workspace_collections(self, items: Sequence[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(list(items), start=1):
            if isinstance(item, dict):
                payload = dict(item)
            else:
                payload = {"title": str(item)}
            payload.setdefault("id", f"collection_{index}")
            payload.setdefault("title", str(payload.get("name") or payload.get("title") or payload.get("id")))
            normalized.append(payload)
        return normalized

    def _normalize_workspace_documents(self, workspace: Dict[str, Any]) -> List[WorkspaceDocument]:
        documents_payload = list(
            workspace.get("documents")
            or workspace.get("items")
            or workspace.get("messages")
            or workspace.get("emails")
            or workspace.get("evidence")
            or []
        )
        workspace_id = str(workspace.get("workspace_id") or workspace.get("id") or workspace.get("dataset_id") or "workspace")
        normalized: List[WorkspaceDocument] = []
        for index, item in enumerate(documents_payload, start=1):
            if not isinstance(item, dict):
                continue
            existing_metadata = dict(item.get("metadata") or {})
            text = str(
                item.get("text")
                or item.get("plain_text")
                or item.get("content")
                or item.get("body")
                or item.get("message")
                or item.get("description")
                or item.get("snippet")
                or ""
            ).strip()
            text_extraction = dict(item.get("text_extraction") or existing_metadata.get("text_extraction") or {})
            if text and not str(text_extraction.get("source") or "").strip():
                text_extraction["source"] = "plain_text"
            title = str(
                item.get("title")
                or item.get("subject")
                or item.get("name")
                or item.get("label")
                or item.get("channel")
                or f"Workspace document {index}"
            ).strip()
            document_id = str(item.get("document_id") or item.get("id") or f"{workspace_id}_doc_{index}")
            normalized.append(
                WorkspaceDocument(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    title=title,
                    text=text,
                    captured_at=str(
                        item.get("captured_at")
                        or item.get("timestamp")
                        or item.get("sent_at")
                        or item.get("created_at")
                        or item.get("date")
                        or ""
                    ),
                    document_number=str(item.get("document_number") or item.get("message_id") or item.get("thread_id") or ""),
                    source_url=str(item.get("source_url") or item.get("source_path") or item.get("url") or ""),
                    metadata={
                        **existing_metadata,
                        "document_type": item.get("document_type") or item.get("item_type") or item.get("source_type"),
                        "page_count": item.get("page_count"),
                        "text_extraction": text_extraction,
                        "classification": {
                            "label": str(item.get("document_type") or item.get("item_type") or item.get("source_type") or "other"),
                            "backend": "workspace_document_classifier",
                            "confidence": 0.5,
                        },
                        "raw": dict(item),
                    },
                )
            )
        return normalized

    def _select_index_documents(self, documents: Sequence[WorkspaceDocument]) -> List[WorkspaceDocument]:
        best_by_key: Dict[str, tuple[int, int, WorkspaceDocument]] = {}
        for document in documents:
            index_title = _document_index_title(document)
            index_text = _document_index_text(document)
            priority = _document_index_priority(document)
            if priority <= 0:
                continue
            if not (str(index_text or "").strip() or str(index_title or "").strip()):
                continue
            metadata = dict(document.metadata or {})
            metadata["retrieval_index"] = {
                "selected": True,
                "priority": priority,
                "title": index_title,
                "source_kind": str((document.metadata.get("text_extraction") or {}).get("source") or "") or "synthetic",
                "evidence_quality": _workspace_document_retrieval_evidence_quality(document),
                "dedupe_key": _workspace_document_dedupe_key(document),
            }
            candidate = WorkspaceDocument(
                document_id=document.document_id,
                workspace_id=document.workspace_id,
                title=index_title or document.title,
                text=index_text,
                captured_at=document.captured_at,
                document_number=document.document_number,
                source_url=document.source_url,
                metadata=metadata,
            )
            dedupe_key = _workspace_document_dedupe_key(document)
            ranking = (priority, len(index_text or ""))
            existing = best_by_key.get(dedupe_key)
            if existing is None or ranking > existing[:2]:
                best_by_key[dedupe_key] = (priority, len(index_text or ""), candidate)
        selected = [item[2] for item in best_by_key.values()]
        selected.sort(
            key=lambda document: (
                str(document.captured_at or ""),
                str(document.document_number or ""),
                str(document.document_id or ""),
            )
        )
        return selected

    def _build_knowledge_graph(
        self,
        dataset_id: str,
        workspace_id: str,
        workspace_name: str,
        source_type: str,
        documents: Sequence[WorkspaceDocument],
    ) -> Dict[str, Any]:
        graph = KnowledgeGraph(source=dataset_id)
        workspace_node_id = f"{dataset_id}:workspace"
        graph.add_entity(
            Entity(
                id=workspace_node_id,
                type="workspace_dataset",
                label=workspace_name,
                properties={"workspace_id": workspace_id, "source_type": source_type},
            )
        )
        for document in documents:
            document_node_id = f"{dataset_id}:document:{_safe_identifier(document.document_id)}"
            graph.add_entity(
                Entity(
                    id=document_node_id,
                    type="workspace_document",
                    label=document.title,
                    properties={
                        "document_id": document.document_id,
                        "workspace_id": document.workspace_id,
                        "captured_at": document.captured_at,
                        "document_number": document.document_number,
                        "source_url": document.source_url,
                    },
                )
            )
            graph.add_relationship(
                Relationship(
                    id=f"{dataset_id}:rel:workspace_contains:{_safe_identifier(document.document_id)}",
                    source=workspace_node_id,
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


def _workspace_document_retrieval_evidence_quality(document: WorkspaceDocument) -> str:
    source = str(_document_text_source(document) or "").strip().lower()
    if source in {"plain_text", "text", "email_body", "message_body", "transcript"}:
        return "plain_text"
    return _document_retrieval_evidence_quality(document)


def _workspace_document_dedupe_key(document: WorkspaceDocument) -> str:
    title = _normalize_workspace_title(_document_index_title(document))
    doc_id = str(document.document_id or "")
    if doc_id and title:
        return f"{doc_id}::{title}"
    if doc_id:
        return doc_id
    if title:
        return title
    return doc_id


def _normalize_workspace_title(title: str | None) -> str:
    return str(title or "").strip().lower()


def _extract_pdf_text(path: Path, *, max_pages: Optional[int] = None) -> Dict[str, Any]:
    backends: List[str] = []
    errors: List[str] = []
    page_texts: List[str] = []
    page_count = 0

    try:
        from pypdf import PdfReader  # type: ignore

        backends.append("pypdf")
        reader = PdfReader(str(path))
        pages = list(reader.pages)
        page_count = len(pages)
        if max_pages is not None:
            pages = pages[: max(0, int(max_pages))]
        for page in pages:
            try:
                page_texts.append(str(page.extract_text() or ""))
            except Exception as exc:
                errors.append(f"pypdf_page_error:{exc}")
    except Exception as exc:
        errors.append(f"pypdf:{exc}")

    if not "".join(page_texts).strip():
        page_texts = []
        try:
            import pdfplumber  # type: ignore

            backends.append("pdfplumber")
            with pdfplumber.open(str(path)) as pdf:
                pages = list(pdf.pages)
                page_count = page_count or len(pages)
                if max_pages is not None:
                    pages = pages[: max(0, int(max_pages))]
                for page in pages:
                    try:
                        page_texts.append(str(page.extract_text() or ""))
                    except Exception as exc:
                        errors.append(f"pdfplumber_page_error:{exc}")
        except Exception as exc:
            errors.append(f"pdfplumber:{exc}")

    if not "".join(page_texts).strip():
        page_texts = []
        try:
            import fitz  # type: ignore

            backends.append("pymupdf")
            document = fitz.open(str(path))
            page_count = page_count or len(document)
            pages = range(len(document))
            if max_pages is not None:
                pages = range(min(len(document), max(0, int(max_pages))))
            for page_index in pages:
                try:
                    page_texts.append(str(document[page_index].get_text() or ""))
                except Exception as exc:
                    errors.append(f"pymupdf_page_error:{exc}")
        except Exception as exc:
            errors.append(f"pymupdf:{exc}")

    return {
        "text": "\n\n".join(text.strip() for text in page_texts if text and text.strip()).strip(),
        "page_count": page_count,
        "backend": backends[-1] if backends else "",
        "errors": errors,
        "error": "; ".join(errors[-3:]),
    }


def _merge_workspace_knowledge_graphs(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(primary or {})
    entity_index: Dict[str, Dict[str, Any]] = {}
    relationship_index: Dict[str, Dict[str, Any]] = {}

    for entity in list((primary or {}).get("entities") or []) + list((secondary or {}).get("entities") or []):
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("id") or entity.get("entity_id") or "")
        if entity_id:
            entity_index[entity_id] = dict(entity)
    for relationship in list((primary or {}).get("relationships") or []) + list((secondary or {}).get("relationships") or []):
        if not isinstance(relationship, dict):
            continue
        relationship_id = str(relationship.get("id") or relationship.get("relationship_id") or "")
        if not relationship_id:
            relationship_id = ":".join(
                [
                    str(relationship.get("source") or ""),
                    str(relationship.get("type") or ""),
                    str(relationship.get("target") or ""),
                ]
            )
        relationship_index[relationship_id] = dict(relationship)
    merged["entities"] = list(entity_index.values())
    merged["relationships"] = list(relationship_index.values())
    return merged


def _build_workspace_formal_logic_metadata(
    dataset: WorkspaceDatasetObject,
    *,
    max_documents: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        from .formal_docket_enrichment import enrich_docket_documents_with_formal_logic

        return enrich_docket_documents_with_formal_logic(
            list(dataset.documents or []),
            docket_id=str(dataset.workspace_id or dataset.dataset_id or "workspace"),
            case_name=str(dataset.workspace_name or dataset.workspace_id or "Workspace"),
            court="workspace",
            max_documents=max_documents,
            max_chars=5000,
        )
    except Exception as exc:
        return {
            "summary": {
                "processed_document_count": 0,
                "skipped_document_count": len(list(dataset.documents or [])),
                "deontic_statement_count": 0,
                "temporal_formula_count": 0,
                "dcec_formula_count": 0,
                "frame_count": 0,
                "proof_count": 0,
            },
            "error": str(exc),
            "source": "workspace_pdf_formal_logic_metadata",
        }


def _workspace_search_result_document_id(result: Dict[str, Any]) -> str:
    return str(result.get("document_id") or result.get("id") or "")


def _workspace_group_document_ids(collection: Dict[str, Any]) -> List[str]:
    raw = collection.get("document_ids") or []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item or "")]


def _workspace_result_score(result: Dict[str, Any]) -> float:
    try:
        return float(result.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _group_workspace_search_results(
    dataset_payload: Dict[str, Any],
    results: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    documents = {
        str(item.get("document_id") or item.get("id") or ""): dict(item)
        for item in list(dataset_payload.get("documents") or [])
        if isinstance(item, dict) and str(item.get("document_id") or item.get("id") or "")
    }
    collections = [dict(item) for item in list(dataset_payload.get("collections") or []) if isinstance(item, dict)]
    collection_by_id = {
        str(collection.get("id") or ""): collection
        for collection in collections
        if str(collection.get("id") or "")
    }
    collection_by_document_id: Dict[str, str] = {}
    for collection in collections:
        collection_id = str(collection.get("id") or "")
        if not collection_id:
            continue
        for document_id in _workspace_group_document_ids(collection):
            collection_by_document_id.setdefault(document_id, collection_id)

    grouped: List[Dict[str, Any]] = []
    grouped_index: Dict[str, int] = {}
    grouped_matches: Dict[str, set[str]] = {}

    for result in results:
        result_payload = dict(result)
        document_id = _workspace_search_result_document_id(result_payload)
        document = dict(documents.get(document_id) or {})
        metadata = dict(document.get("metadata") or {})
        collection_id = str(metadata.get("collection_id") or collection_by_document_id.get(document_id) or "")
        if not collection_id:
            collection_id = f"document:{document_id}" if document_id else f"result:{len(grouped) + 1}"

        group_position = grouped_index.get(collection_id)
        if group_position is None:
            collection = dict(collection_by_id.get(collection_id) or {})
            group_document_ids = _workspace_group_document_ids(collection)
            if not group_document_ids and document_id:
                group_document_ids = [document_id]
            group_documents: List[Dict[str, Any]] = []
            for group_document_id in group_document_ids:
                group_document = dict(documents.get(group_document_id) or {})
                group_metadata = dict(group_document.get("metadata") or {})
                group_documents.append(
                    {
                        "document_id": group_document_id,
                        "title": str(group_document.get("title") or group_document_id),
                        "document_type": str(group_metadata.get("document_type") or group_document.get("document_type") or ""),
                        "parent_document_id": str(group_metadata.get("parent_document_id") or group_document_id),
                        "is_match": group_document_id == document_id,
                    }
                )
            grouped.append(
                {
                    "group_id": collection_id,
                    "group_title": str(collection.get("title") or document.get("title") or document_id or collection_id),
                    "source_type": str(collection.get("source_type") or dataset_payload.get("source_type") or "workspace"),
                    "parent_document_id": str(collection.get("parent_document_id") or metadata.get("parent_document_id") or document_id),
                    "document_ids": group_document_ids,
                    "documents": group_documents,
                    "matched_results": [result_payload],
                    "match_count": 1,
                    "top_score": _workspace_result_score(result_payload),
                }
            )
            grouped_index[collection_id] = len(grouped) - 1
            grouped_matches[collection_id] = {document_id} if document_id else set()
            continue

        group = grouped[group_position]
        group["matched_results"].append(result_payload)
        group["match_count"] = int(group.get("match_count") or 0) + 1
        group["top_score"] = max(float(group.get("top_score") or 0.0), _workspace_result_score(result_payload))
        if document_id and document_id not in grouped_matches[collection_id]:
            grouped_matches[collection_id].add(document_id)
            for group_document in list(group.get("documents") or []):
                if str(group_document.get("document_id") or "") == document_id:
                    group_document["is_match"] = True
                    break

    return grouped


def search_workspace_dataset_bm25(
    dataset: WorkspaceDatasetObject | Dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
) -> Dict[str, Any]:
    dataset_payload = dataset.to_dict() if isinstance(dataset, WorkspaceDatasetObject) else dict(dataset)
    bm25_index = dict(dataset_payload.get("bm25_index") or {})
    documents = list(bm25_index.get("documents") or [])
    results = bm25_search_documents(query, documents, top_k=top_k)
    grouped_results = _group_workspace_search_results(dataset_payload, results)
    return {
        "query": query,
        "top_k": top_k,
        "results": results,
        "grouped_results": grouped_results,
        "group_count": len(grouped_results),
        "result_count": len(results),
        "source": "local_bm25",
    }


def search_workspace_dataset_vector(
    dataset: WorkspaceDatasetObject | Dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
    vector_dimension: int = 32,
) -> Dict[str, Any]:
    dataset_payload = dataset.to_dict() if isinstance(dataset, WorkspaceDatasetObject) else dict(dataset)
    vector_index = dict(dataset_payload.get("vector_index") or {})
    items = list(vector_index.get("items") or [])
    builder = WorkspaceDatasetBuilder(vector_dimension=vector_dimension)
    query_vector = embed_query_for_backend(
        query,
        backend=str(vector_index.get("backend") or "local_hashed_term_projection"),
        dimension=int(vector_index.get("dimension") or builder.vector_dimension),
        provider=str(vector_index.get("provider") or "") or None,
        model_name=str(vector_index.get("model_name") or "") or None,
        device=str(vector_index.get("device") or "") or None,
    )
    scored: List[Dict[str, Any]] = []
    for item in items:
        vector = list(item.get("vector") or [])
        score = vector_dot(query_vector, vector)
        scored.append(
            {
                "document_id": item.get("document_id"),
                "title": item.get("title"),
                "captured_at": item.get("date_filed") or item.get("captured_at"),
                "document_number": item.get("document_number"),
                "score": score,
                "backend": str(vector_index.get("backend") or "local_hashed_term_projection"),
            }
        )
    scored.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    results = scored[:top_k]
    grouped_results = _group_workspace_search_results(dataset_payload, results)
    return {
        "query": query,
        "top_k": top_k,
        "results": results,
        "grouped_results": grouped_results,
        "group_count": len(grouped_results),
        "result_count": len(results),
    }


def summarize_workspace_dataset(dataset: WorkspaceDatasetObject | Dict[str, Any]) -> Dict[str, Any]:
    dataset_payload = dataset.to_dict() if isinstance(dataset, WorkspaceDatasetObject) else dict(dataset)
    metadata = dict(dataset_payload.get("metadata") or {})
    formal_summary = dict(metadata.get("formal_logic_summary") or (metadata.get("formal_logic") or {}).get("summary") or {})
    return {
        "dataset_id": str(dataset_payload.get("dataset_id") or ""),
        "workspace_id": str(dataset_payload.get("workspace_id") or ""),
        "workspace_name": str(dataset_payload.get("workspace_name") or ""),
        "source_type": str(dataset_payload.get("source_type") or "workspace"),
        "document_count": len(list(dataset_payload.get("documents") or [])),
        "collection_count": len(list(dataset_payload.get("collections") or [])),
        "knowledge_graph_entity_count": len(list((dataset_payload.get("knowledge_graph") or {}).get("entities") or [])),
        "knowledge_graph_relationship_count": len(list((dataset_payload.get("knowledge_graph") or {}).get("relationships") or [])),
        "bm25_document_count": int((dataset_payload.get("bm25_index") or {}).get("document_count") or 0),
        "vector_document_count": int((dataset_payload.get("vector_index") or {}).get("document_count") or 0),
        "formal_logic_processed_document_count": int(formal_summary.get("processed_document_count") or 0),
        "deontic_statement_count": int(formal_summary.get("deontic_statement_count") or 0),
        "temporal_formula_count": int(formal_summary.get("temporal_formula_count") or 0),
        "dcec_formula_count": int(formal_summary.get("dcec_formula_count") or 0),
        "frame_logic_count": int(formal_summary.get("frame_count") or 0),
        "proof_count": int(formal_summary.get("proof_count") or 0),
        "metadata": metadata,
    }


def _load_workspace_bundle_rows(parquet_path: str | Path) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq

    table = pq.read_table(Path(parquet_path))
    return [dict(row) for row in table.to_pylist()]


def _decode_workspace_bundle_section(
    rows: Sequence[Dict[str, Any]],
    section: str,
) -> List[Dict[str, Any]]:
    decoded: List[Dict[str, Any]] = []
    for row in rows:
        if str(row.get("section") or "") != section:
            continue
        payload_json = str(row.get("payload_json") or "").strip()
        if not payload_json:
            continue
        decoded.append(dict(json.loads(payload_json)))
    return decoded


def load_workspace_dataset_single_parquet(parquet_path: str | Path) -> Dict[str, Any]:
    rows = _load_workspace_bundle_rows(parquet_path)
    dataset_core_rows = _decode_workspace_bundle_section(rows, "dataset_core")
    dataset_core = dict(dataset_core_rows[0]) if dataset_core_rows else {}
    documents = _decode_workspace_bundle_section(rows, "documents")
    collections = _decode_workspace_bundle_section(rows, "collections")
    knowledge_graph_entities = _decode_workspace_bundle_section(rows, "knowledge_graph_entities")
    knowledge_graph_relationships = _decode_workspace_bundle_section(rows, "knowledge_graph_relationships")
    bm25_documents = _decode_workspace_bundle_section(rows, "bm25_documents")
    vector_items = _decode_workspace_bundle_section(rows, "vector_items")
    return {
        "dataset_id": str(dataset_core.get("dataset_id") or ""),
        "workspace_id": str(dataset_core.get("workspace_id") or ""),
        "workspace_name": str(dataset_core.get("workspace_name") or ""),
        "source_type": str(dataset_core.get("source_type") or "workspace"),
        "documents": documents,
        "collections": collections,
        "knowledge_graph": {
            "entities": knowledge_graph_entities,
            "relationships": knowledge_graph_relationships,
        },
        "bm25_index": {
            "backend": "local_bm25",
            "documents": bm25_documents,
            "document_count": len(bm25_documents),
        },
        "vector_index": {
            "backend": "local_hashed_term_projection",
            "items": vector_items,
            "document_count": len(vector_items),
        },
        "metadata": dict(dataset_core.get("metadata") or {}),
        "bundle": {
            "parquet_path": str(Path(parquet_path)),
            "row_count": len(rows),
            "sections": sorted({str(row.get("section") or "") for row in rows if str(row.get("section") or "")} ),
        },
    }


def load_workspace_dataset_single_parquet_summary(parquet_path: str | Path) -> Dict[str, Any]:
    dataset = load_workspace_dataset_single_parquet(parquet_path)
    summary = summarize_workspace_dataset(dataset)
    summary["bundle"] = dict(dataset.get("bundle") or {})
    return summary


def inspect_workspace_dataset_single_parquet(parquet_path: str | Path) -> Dict[str, Any]:
    dataset = load_workspace_dataset_single_parquet(parquet_path)
    bundle = dict(dataset.get("bundle") or {})
    return {
        "dataset_id": str(dataset.get("dataset_id") or ""),
        "workspace_id": str(dataset.get("workspace_id") or ""),
        "workspace_name": str(dataset.get("workspace_name") or ""),
        "source_type": str(dataset.get("source_type") or "workspace"),
        "row_count": int(bundle.get("row_count") or 0),
        "sections": list(bundle.get("sections") or []),
        "document_count": len(list(dataset.get("documents") or [])),
        "collection_count": len(list(dataset.get("collections") or [])),
        "knowledge_graph_entity_count": len(list((dataset.get("knowledge_graph") or {}).get("entities") or [])),
        "knowledge_graph_relationship_count": len(list((dataset.get("knowledge_graph") or {}).get("relationships") or [])),
        "bm25_document_count": int((dataset.get("bm25_index") or {}).get("document_count") or 0),
        "vector_document_count": int((dataset.get("vector_index") or {}).get("document_count") or 0),
        "parquet_path": str(Path(parquet_path)),
        "source": "workspace_dataset_single_parquet_inspection",
    }


def render_workspace_dataset_single_parquet_report(
    parquet_path: str | Path | Dict[str, Any],
    *,
    report_format: str = "markdown",
) -> str:
    inspection = (
        dict(parquet_path)
        if isinstance(parquet_path, dict)
        else inspect_workspace_dataset_single_parquet(parquet_path)
    )
    normalized_format = str(report_format or "markdown").strip().lower()
    if normalized_format == "json":
        return json.dumps(inspection, indent=2, ensure_ascii=False) + "\n"

    lines = [
        "Workspace Dataset Bundle Report",
        f"Workspace ID: {str(inspection.get('workspace_id') or '')}",
        f"Workspace Name: {str(inspection.get('workspace_name') or '')}",
        f"Source Type: {str(inspection.get('source_type') or '')}",
        f"Parquet Path: {str(inspection.get('parquet_path') or '')}",
        f"Row Count: {int(inspection.get('row_count') or 0)}",
        f"Sections: {', '.join(str(item) for item in list(inspection.get('sections') or []))}",
        f"Document Count: {int(inspection.get('document_count') or 0)}",
        f"Collection Count: {int(inspection.get('collection_count') or 0)}",
        f"Knowledge Graph Entities: {int(inspection.get('knowledge_graph_entity_count') or 0)}",
        f"Knowledge Graph Relationships: {int(inspection.get('knowledge_graph_relationship_count') or 0)}",
        f"BM25 Documents: {int(inspection.get('bm25_document_count') or 0)}",
        f"Vector Documents: {int(inspection.get('vector_document_count') or 0)}",
    ]
    if normalized_format == "text":
        return "\n".join(lines) + "\n"
    if normalized_format == "markdown":
        markdown_lines = [
            "# Workspace Dataset Bundle Report",
            "",
            *[f"- {line}" for line in lines[1:]],
        ]
        return "\n".join(markdown_lines) + "\n"
    raise ValueError(f"Unsupported workspace dataset report format: {report_format}")


def ingest_workspace_pdf_directory(
    directory: str | Path,
    output_parquet: str | Path,
    *,
    workspace_id: Optional[str] = None,
    workspace_name: Optional[str] = None,
    source_type: str = "pdf_directory",
    vector_dimension: int = 16,
    include_formal_logic: bool = True,
    formal_logic_max_documents: Optional[int] = None,
    max_pdf_pages: Optional[int] = None,
    max_pdf_chars: Optional[int] = None,
    glob_pattern: str = "*.pdf",
    exclude_dirs: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    builder = WorkspaceDatasetBuilder(vector_dimension=int(vector_dimension or 16))
    dataset = builder.build_from_pdf_directory(
        directory,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        source_type=source_type,
        include_formal_logic=include_formal_logic,
        formal_logic_max_documents=formal_logic_max_documents,
        max_pdf_pages=max_pdf_pages,
        max_pdf_chars=max_pdf_chars,
        glob_pattern=glob_pattern,
        exclude_dirs=exclude_dirs,
    )
    export_result = export_workspace_dataset_single_parquet(dataset, output_parquet)
    return {
        **dict(export_result),
        "summary": summarize_workspace_dataset(dataset),
        "dataset_id": dataset.dataset_id,
        "workspace_id": dataset.workspace_id,
        "workspace_name": dataset.workspace_name,
        "source": "workspace_pdf_directory_ingest",
    }


def export_workspace_dataset_single_parquet(
    dataset: WorkspaceDatasetObject | Dict[str, Any],
    output_path: str | Path,
) -> Dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    dataset_payload = dataset.to_dict() if isinstance(dataset, WorkspaceDatasetObject) else dict(dataset)
    documents = [dict(item) for item in list(dataset_payload.get("documents") or []) if isinstance(item, dict)]
    knowledge_graph = dict(dataset_payload.get("knowledge_graph") or {})
    bm25_documents = [dict(item) for item in list((dataset_payload.get("bm25_index") or {}).get("documents") or []) if isinstance(item, dict)]
    vector_items = [dict(item) for item in list((dataset_payload.get("vector_index") or {}).get("items") or []) if isinstance(item, dict)]
    collections = [dict(item) for item in list(dataset_payload.get("collections") or []) if isinstance(item, dict)]

    section_map: List[tuple[str, List[Dict[str, Any]]]] = [
        (
            "dataset_core",
            [
                {
                    "dataset_id": str(dataset_payload.get("dataset_id") or ""),
                    "workspace_id": str(dataset_payload.get("workspace_id") or ""),
                    "workspace_name": str(dataset_payload.get("workspace_name") or ""),
                    "source_type": str(dataset_payload.get("source_type") or "workspace"),
                    "metadata": dict(dataset_payload.get("metadata") or {}),
                }
            ],
        ),
        ("collections", collections),
        ("documents", documents),
        ("knowledge_graph_entities", [dict(item) for item in list(knowledge_graph.get("entities") or []) if isinstance(item, dict)]),
        ("knowledge_graph_relationships", [dict(item) for item in list(knowledge_graph.get("relationships") or []) if isinstance(item, dict)]),
        ("bm25_documents", bm25_documents),
        ("vector_items", vector_items),
    ]

    bundle_rows: List[Dict[str, Any]] = []
    dataset_id = str(dataset_payload.get("dataset_id") or "")
    workspace_id = str(dataset_payload.get("workspace_id") or "")
    workspace_name = str(dataset_payload.get("workspace_name") or "")
    source_type = str(dataset_payload.get("source_type") or "workspace")
    for section, rows in section_map:
        for index, row in enumerate(rows, start=1):
            payload = dict(row)
            bundle_rows.append(
                {
                    "dataset_id": dataset_id,
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "source_type": source_type,
                    "section": section,
                    "row_index": index,
                    "row_id": str(payload.get("document_id") or payload.get("id") or payload.get("entity_id") or payload.get("relationship_id") or f"{section}_{index}"),
                    "title": str(payload.get("title") or payload.get("label") or payload.get("workspace_name") or ""),
                    "document_number": str(payload.get("document_number") or ""),
                    "source_url": str(payload.get("source_url") or payload.get("path_or_url") or payload.get("source_path") or ""),
                    "text": str(payload.get("text") or ""),
                    "payload_json": json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str),
                }
            )
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(bundle_rows)
    pq.write_table(table, output_file)
    return {
        "parquet_path": str(output_file),
        "row_count": len(bundle_rows),
        "section_count": len(section_map),
        "file_size_bytes": output_file.stat().st_size if output_file.exists() else 0,
    }
