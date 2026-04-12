"""GraphRAG and DuckDB corpus helpers for email manifests."""

from __future__ import annotations

import importlib
import json
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from complaint_phases.knowledge_graph import KnowledgeGraphBuilder
from ipfs_datasets_py.processors.multimedia.attachment_text_extractor import extract_attachment_text

try:
    from ipfs_datasets_py.processors.multimedia.email_duckdb_index import (
        build_email_duckdb_index as _build_email_duckdb_index,
        search_email_duckdb_index as _search_email_duckdb_index,
    )
except Exception:
    _repo_root = Path(__file__).resolve().parents[3]
    if _repo_root.exists():
        for _module_name in list(sys.modules):
            if _module_name == "ipfs_datasets_py" or _module_name.startswith("ipfs_datasets_py."):
                sys.modules.pop(_module_name, None)
        sys.path.insert(0, str(_repo_root))
        try:
            _module = importlib.import_module("ipfs_datasets_py.processors.multimedia.email_duckdb_index")
            _build_email_duckdb_index = getattr(_module, "build_email_duckdb_index", None)
            _search_email_duckdb_index = getattr(_module, "search_email_duckdb_index", None)
        except Exception:
            _build_email_duckdb_index = None
            _search_email_duckdb_index = None
    else:
        _build_email_duckdb_index = None
        _search_email_duckdb_index = None


def _participants_from_eml(bundle_dir: Path) -> list[str]:
    eml_path = bundle_dir / "message.eml"
    if not eml_path.exists():
        return []
    try:
        message = BytesParser(policy=policy.default).parsebytes(eml_path.read_bytes())
    except Exception:
        return []
    participants: list[str] = []
    seen: set[str] = set()
    for header_name in ("from", "to", "cc", "bcc", "reply-to", "sender"):
        header = message.get(header_name)
        header_addresses = getattr(header, "addresses", ()) or ()
        for entry in header_addresses:
            username = str(getattr(entry, "username", "") or "").strip()
            domain = str(getattr(entry, "domain", "") or "").strip()
            if not username or not domain:
                continue
            address = f"{username}@{domain}".lower()
            if address in seen:
                continue
            seen.add(address)
            participants.append(address)
    return participants


def _body_from_eml(bundle_dir: Path) -> str:
    eml_path = bundle_dir / "message.eml"
    if not eml_path.exists():
        return ""
    try:
        message = BytesParser(policy=policy.default).parsebytes(eml_path.read_bytes())
    except Exception:
        return ""
    body_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if (part.get_content_disposition() or "").lower() == "attachment":
                continue
            if part.get_content_type() != "text/plain":
                continue
            try:
                body_parts.append(str(part.get_content() or ""))
            except Exception:
                payload = part.get_payload(decode=True) or b""
                body_parts.append(payload.decode("utf-8", errors="ignore"))
    else:
        try:
            body_parts.append(str(message.get_content() or ""))
        except Exception:
            payload = message.get_payload(decode=True) or b""
            body_parts.append(payload.decode("utf-8", errors="ignore"))
    return "\n".join(part.strip() for part in body_parts if str(part or "").strip()).strip()


def _email_record_to_corpus_text(record: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Email subject: {record.get('subject') or ''}")
    lines.append(f"From: {record.get('from') or ''}")
    lines.append(f"To: {record.get('to') or ''}")
    lines.append(f"Cc: {record.get('cc') or ''}")
    lines.append(f"Date: {record.get('date') or ''}")
    participants = ", ".join(record.get("participants") or [])
    if participants:
        lines.append(f"Participants: {participants}")
    if record.get("message_id_header"):
        lines.append(f"Message-ID: {record.get('message_id_header')}")
    if record.get("body_text"):
        lines.extend(["Email body:", str(record.get("body_text") or "")])
    for path_str in record.get("attachment_paths") or []:
        path = Path(path_str)
        lines.append(f"Attachment filename: {path.name}")
        extraction = extract_attachment_text(path, use_ocr=True)
        attachment_text = str(extraction.get("text") or "").strip()
        if attachment_text:
            lines.append(f"Attachment text from {path.name}: {attachment_text}")
    return "\n".join(line for line in lines if line.strip()).strip()


def build_email_graphrag_artifacts(
    *,
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    emit_duckdb_index: bool = True,
    append_duckdb_index: bool = False,
    include_attachment_text_in_search: bool = True,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path).expanduser().resolve()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    records = list(manifest.get("emails") or [])
    run_dir = manifest_file.parent
    graphrag_dir = Path(output_dir).expanduser().resolve() if output_dir else run_dir / "graphrag"
    graphrag_dir.mkdir(parents=True, exist_ok=True)

    email_corpus_records: list[dict[str, Any]] = []
    combined_sections: list[str] = []
    for index, record in enumerate(records, start=1):
        bundle_dir = Path(record.get("bundle_dir") or "")
        parsed_participants = _participants_from_eml(bundle_dir) if bundle_dir else []
        merged_participants: list[str] = []
        seen_participants: set[str] = set()
        for participant in list(record.get("participants") or []) + parsed_participants:
            cleaned = str(participant or "").strip().lower()
            if not cleaned or cleaned in seen_participants:
                continue
            seen_participants.add(cleaned)
            merged_participants.append(cleaned)
        record_for_corpus = dict(record)
        record_for_corpus["participants"] = merged_participants
        record_for_corpus["body_text"] = _body_from_eml(bundle_dir) if bundle_dir else ""
        corpus_text = _email_record_to_corpus_text(record_for_corpus)
        entry = {
            "index": index,
            "subject": record.get("subject", ""),
            "from": record.get("from", ""),
            "to": record.get("to", ""),
            "date": record.get("date"),
            "bundle_dir": record.get("bundle_dir"),
            "attachment_paths": list(record.get("attachment_paths") or []),
            "participants": merged_participants,
            "corpus_text": corpus_text,
        }
        email_corpus_records.append(entry)
        if corpus_text:
            combined_sections.append(f"Email record {index}\n{corpus_text}")

    combined_corpus = "\n\n".join(section for section in combined_sections if section.strip())
    graph = KnowledgeGraphBuilder().build_from_text(combined_corpus)

    graph_path = graphrag_dir / "email_knowledge_graph.json"
    graph.to_json(str(graph_path))

    corpus_path = graphrag_dir / "email_corpus_records.json"
    corpus_path.write_text(json.dumps(email_corpus_records, indent=2, ensure_ascii=False), encoding="utf-8")

    duckdb_index_summary: dict[str, Any] | None = None
    if emit_duckdb_index:
        if _build_email_duckdb_index is None:
            duckdb_index_summary = {"status": "duckdb_index_unavailable"}
        else:
            try:
                duckdb_index_summary = _build_email_duckdb_index(
                    manifest_path=manifest_file,
                    output_dir=graphrag_dir / "duckdb",
                    include_attachment_text=include_attachment_text_in_search,
                    append=append_duckdb_index,
                )
            except ImportError as exc:
                duckdb_index_summary = {"status": "duckdb_unavailable", "error": str(exc)}

    summary = {
        "manifest_path": str(manifest_file),
        "graphrag_dir": str(graphrag_dir),
        "email_count": len(records),
        "attachment_total": sum(len(record.get("attachment_paths") or []) for record in records),
        "knowledge_graph_summary": graph.summary(),
        "graph_path": str(graph_path),
        "corpus_records_path": str(corpus_path),
        "duckdb_index": duckdb_index_summary,
        "include_attachment_text_in_search": bool(include_attachment_text_in_search),
    }
    summary_path = graphrag_dir / "email_graphrag_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return summary


def build_email_duckdb_artifacts(
    *,
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    include_attachment_text: bool = True,
    append: bool = False,
) -> dict[str, Any]:
    if _build_email_duckdb_index is None:
        return {"status": "duckdb_index_unavailable", "manifest_path": str(Path(manifest_path).expanduser().resolve())}
    try:
        return _build_email_duckdb_index(
            manifest_path=manifest_path,
            output_dir=output_dir,
            include_attachment_text=include_attachment_text,
            append=append,
        )
    except ImportError as exc:
        return {
            "status": "duckdb_unavailable",
            "manifest_path": str(Path(manifest_path).expanduser().resolve()),
            "error": str(exc),
        }


def search_email_graphrag_duckdb(
    *,
    index_path: str | Path,
    query: str,
    limit: int = 20,
    ranking: str = "bm25",
    bm25_k1: float = 1.2,
    bm25_b: float = 0.75,
) -> dict[str, Any]:
    if _search_email_duckdb_index is None:
        return {"status": "duckdb_index_unavailable", "query": query, "result_count": 0, "results": []}
    return _search_email_duckdb_index(
        index_path=index_path,
        query=query,
        limit=limit,
        ranking=ranking,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
    )


__all__ = ["build_email_duckdb_artifacts", "build_email_graphrag_artifacts", "search_email_graphrag_duckdb"]
