"""Email workspace import, merge, and corpus-management helpers.

This module centralizes the reusable email-evidence workflow that had grown in
repo-local scripts:

- importing local ``.eml`` directories into normalized bundle manifests
- merging multiple email manifests into one deduplicated corpus manifest
- rebuilding GraphRAG/DuckDB artifacts for a manifest-backed email corpus
- searching a manifest-backed DuckDB email corpus

The lower-level parsing and indexing primitives remain in the multimedia
processors package, while this module provides the legal/workspace-oriented
orchestration layer.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..multimedia.email_processor import EmailProcessor


def _slugify(value: str, *, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip(".-")
    return cleaned or fallback


def _sanitize_filename(filename: str, fallback: str) -> str:
    raw = str(filename or "").strip()
    if not raw:
        return fallback
    raw = raw.replace("/", "_").replace("\\", "_").replace("\x00", "")
    return _slugify(raw, fallback=fallback)


def _normalize_address_values(values: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        for _display, address in getaddresses([str(value or "")]):
            cleaned = address.strip().lower()
            if cleaned:
                normalized.add(cleaned)
    return normalized


def _message_participants(email_message: EmailMessage) -> set[str]:
    return _normalize_address_values(
        [
            email_message.get("From", ""),
            email_message.get("To", ""),
            email_message.get("Cc", ""),
            email_message.get("Reply-To", ""),
            email_message.get("Sender", ""),
        ]
    )


def _extract_attachment_bytes(part: email.message.Message) -> bytes:
    payload = part.get_payload(decode=True)
    return payload or b""


def _collect_message_text(email_message: EmailMessage) -> str:
    parts: list[str] = []
    for key in ("Subject", "From", "To", "Cc", "Reply-To"):
        value = email_message.get(key, "")
        if value:
            parts.append(str(value))
    if email_message.is_multipart():
        for part in email_message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename()
                if filename:
                    parts.append(filename)
                continue
            if part.get_content_type() != "text/plain":
                continue
            try:
                text = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="ignore")
            if text:
                parts.append(str(text))
    else:
        try:
            text = email_message.get_content()
        except Exception:
            payload = email_message.get_payload(decode=True) or b""
            charset = email_message.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="ignore")
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _tokenize_text(value: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'_-]*", str(value or "").lower()) if len(token) >= 3]


def build_complaint_terms(
    *,
    complaint_query: str = "",
    complaint_keywords: Sequence[str] | None = None,
) -> list[str]:
    terms = _tokenize_text(complaint_query)
    for keyword in list(complaint_keywords or []):
        terms.extend(_tokenize_text(keyword))
    counts = Counter(terms)
    return [term for term, _count in counts.most_common()]


def score_email_relevance(email_message: EmailMessage, complaint_terms: Sequence[str]) -> dict[str, Any]:
    normalized_terms = [str(term or "").strip().lower() for term in complaint_terms if str(term or "").strip()]
    if not normalized_terms:
        return {"score": 0.0, "matched_terms": [], "matched_fields": []}
    subject = str(email_message.get("Subject", "") or "")
    body_text = _collect_message_text(email_message)
    subject_tokens = set(_tokenize_text(subject))
    body_tokens = set(_tokenize_text(body_text))
    matched_subject_terms = [term for term in normalized_terms if term in subject_tokens]
    matched_body_terms = [term for term in normalized_terms if term in body_tokens and term not in matched_subject_terms]
    matched_fields: list[str] = []
    if matched_subject_terms:
        matched_fields.append("subject")
    if matched_body_terms:
        matched_fields.append("body")
    return {
        "score": float(len(matched_subject_terms) * 3 + len(matched_body_terms)),
        "matched_terms": matched_subject_terms + matched_body_terms,
        "matched_fields": matched_fields,
    }


def save_email_bundle(
    *,
    root_dir: str | Path,
    folder_name: str,
    email_message: EmailMessage,
    raw_bytes: bytes,
    parsed_email: dict[str, Any],
    sequence_number: int,
) -> dict[str, Any]:
    root_path = Path(root_dir).expanduser().resolve()
    message_key = parsed_email.get("message_id_header") or hashlib.sha256(raw_bytes).hexdigest()[:16]
    subject_slug = _slugify(str(parsed_email.get("subject") or "email"), fallback="email")
    bundle_dir = root_path / f"{int(sequence_number):04d}-{subject_slug}-{_slugify(str(message_key), fallback='message')}"
    attachments_dir = bundle_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    eml_path = bundle_dir / "message.eml"
    eml_path.write_bytes(raw_bytes)

    attachment_records: list[dict[str, Any]] = []
    seen_names: dict[str, int] = {}
    for index, part in enumerate(email_message.walk(), start=1):
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            continue
        filename = part.get_filename() or f"attachment-{index}.bin"
        safe_name = _sanitize_filename(filename, f"attachment-{index}.bin")
        prior_count = seen_names.get(safe_name, 0)
        seen_names[safe_name] = prior_count + 1
        if prior_count:
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix
            safe_name = f"{stem}-{prior_count + 1}{suffix}"
        payload = _extract_attachment_bytes(part)
        attachment_path = attachments_dir / safe_name
        attachment_path.write_bytes(payload)
        attachment_records.append(
            {
                "filename": safe_name,
                "path": str(attachment_path),
                "size": len(payload),
                "content_type": part.get_content_type(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    parsed_payload = {
        "folder": str(folder_name or ""),
        "date_token": str(parsed_email.get("date") or datetime.now(UTC).isoformat()),
        "participants": sorted(_message_participants(email_message)),
        "attachment_count": len(attachment_records),
        **dict(parsed_email),
    }
    parsed_path = bundle_dir / "message.json"
    parsed_path.write_text(json.dumps(parsed_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "folder": str(folder_name or ""),
        "source_type": "gmail_email",
        "bundle_dir": str(bundle_dir),
        "email_path": str(eml_path),
        "parsed_path": str(parsed_path),
        "participants": sorted(_message_participants(email_message)),
        "subject": parsed_email.get("subject", ""),
        "date": parsed_email.get("date"),
        "from": parsed_email.get("from", ""),
        "to": parsed_email.get("to", ""),
        "cc": parsed_email.get("cc", ""),
        "message_id_header": parsed_email.get("message_id_header", ""),
        "text_content": parsed_email.get("body_text", ""),
        "attachment_paths": [item["path"] for item in attachment_records],
        "attachments": attachment_records,
        "evidence_title": parsed_email.get("subject") or f"Email from {parsed_email.get('from', '')}",
    }


def _iter_eml_files(root: Path, *, recursive: bool) -> list[Path]:
    pattern = "**/*.eml" if recursive else "*.eml"
    return sorted(path for path in root.glob(pattern) if path.is_file())


def import_local_eml_directory(
    *,
    source_dir: str | Path,
    output_dir: str | Path,
    case_slug: str,
    recursive: bool = False,
    complaint_query: str = "",
    complaint_keywords: Sequence[str] | None = None,
    min_relevance_score: float = 0.0,
) -> dict[str, object]:
    source_root = Path(source_dir).expanduser().resolve()
    output_root = Path(output_dir).expanduser().resolve()
    run_dir = output_root / case_slug
    run_dir.mkdir(parents=True, exist_ok=True)

    processor = EmailProcessor(protocol="eml")
    complaint_terms = build_complaint_terms(
        complaint_query=str(complaint_query or ""),
        complaint_keywords=list(complaint_keywords or []),
    )

    records: list[dict[str, object]] = []
    scanned_count = 0
    for eml_path in _iter_eml_files(source_root, recursive=recursive):
        scanned_count += 1
        raw_bytes = eml_path.read_bytes()
        email_message = email.message_from_bytes(raw_bytes, policy=email.policy.default)
        parsed = processor._parse_email_message(email_message, include_attachments=True)
        relevance = score_email_relevance(email_message, complaint_terms)
        if complaint_terms and float(relevance["score"] or 0.0) < float(min_relevance_score):
            continue
        bundle_record = save_email_bundle(
            root_dir=run_dir,
            folder_name=str(source_root),
            email_message=email_message,
            raw_bytes=raw_bytes,
            parsed_email=parsed,
            sequence_number=len(records) + 1,
        )
        bundle_record["relevance_score"] = relevance["score"]
        bundle_record["matched_terms"] = relevance["matched_terms"]
        bundle_record["matched_fields"] = relevance["matched_fields"]
        bundle_record["cache_hit"] = False
        bundle_record["raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        bundle_record["source_eml_path"] = str(eml_path)
        records.append(bundle_record)

    manifest = {
        "status": "success",
        "server": "local_workspace",
        "username": "",
        "auth_mode": "local_eml_import",
        "folders": [str(source_root)],
        "search": "LOCAL_EML_DIRECTORY_IMPORT",
        "complaint_terms": complaint_terms,
        "min_relevance_score": float(min_relevance_score),
        "address_targets": [],
        "from_address_targets": [],
        "recipient_address_targets": [],
        "domain_targets": [],
        "from_domain_targets": [],
        "recipient_domain_targets": [],
        "scanned_message_count": scanned_count,
        "matched_email_count": len(records),
        "output_dir": str(run_dir),
        "cache_index_path": "",
        "emails": records,
    }
    manifest_path = run_dir / "email_import_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"manifest_path": str(manifest_path), "output_dir": str(run_dir), "email_count": len(records)}


def _merge_terms(manifests: list[dict[str, Any]]) -> list[str]:
    counts: Counter[str] = Counter()
    for manifest in manifests:
        for term in list(manifest.get("complaint_terms") or []):
            cleaned = str(term or "").strip().lower()
            if cleaned:
                counts[cleaned] += 1
    return [term for term, _count in counts.most_common()]


def _record_identity(record: dict[str, Any]) -> str:
    for key in ("message_id_header", "message_key", "raw_sha256", "email_path", "source_eml_path"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return json.dumps(
        {
            "subject": record.get("subject"),
            "date": record.get("date"),
            "from": record.get("from"),
            "to": record.get("to"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def merge_email_manifests(
    *,
    manifest_paths: Sequence[str | Path],
    output_dir: str | Path,
    case_slug: str,
) -> dict[str, Any]:
    manifest_files = [Path(path).expanduser().resolve() for path in manifest_paths]
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in manifest_files]

    seen: set[str] = set()
    merged_records: list[dict[str, Any]] = []
    source_records = 0
    duplicate_count = 0
    for manifest_file, manifest in zip(manifest_files, manifests):
        for record in list(manifest.get("emails") or []):
            source_records += 1
            identity = _record_identity(record)
            if identity in seen:
                duplicate_count += 1
                continue
            seen.add(identity)
            merged_record = dict(record)
            merged_record["source_manifest_path"] = str(manifest_file)
            merged_records.append(merged_record)

    merged_records.sort(
        key=lambda record: (
            str(record.get("date") or ""),
            str(record.get("subject") or ""),
            str(record.get("message_id_header") or record.get("raw_sha256") or ""),
        )
    )

    output_root = Path(output_dir).expanduser().resolve()
    run_dir = output_root / case_slug
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "status": "success",
        "server": "local_workspace",
        "username": "",
        "auth_mode": "merged_email_manifests",
        "folders": [str(path.parent) for path in manifest_files],
        "search": "MERGED_EMAIL_MANIFESTS",
        "complaint_terms": _merge_terms(manifests),
        "min_relevance_score": max(float(manifest.get("min_relevance_score") or 0.0) for manifest in manifests) if manifests else 0.0,
        "address_targets": [],
        "from_address_targets": [],
        "recipient_address_targets": [],
        "domain_targets": [],
        "from_domain_targets": [],
        "recipient_domain_targets": [],
        "scanned_message_count": source_records,
        "matched_email_count": len(merged_records),
        "output_dir": str(run_dir),
        "cache_index_path": "",
        "source_manifest_paths": [str(path) for path in manifest_files],
        "duplicate_email_count": duplicate_count,
        "emails": merged_records,
    }
    manifest_path = run_dir / "email_import_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "manifest_path": str(manifest_path),
        "output_dir": str(run_dir),
        "email_count": len(merged_records),
        "duplicate_email_count": duplicate_count,
    }


def build_email_workspace_corpus(
    *,
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    include_attachment_text_in_search: bool = True,
    append_duckdb_index: bool = False,
) -> dict[str, Any]:
    from .email_corpus import build_email_graphrag_artifacts

    return build_email_graphrag_artifacts(
        manifest_path=manifest_path,
        output_dir=output_dir,
        append_duckdb_index=append_duckdb_index,
        include_attachment_text_in_search=include_attachment_text_in_search,
    )


def search_email_workspace_corpus(
    *,
    index_path: str | Path,
    query: str,
    limit: int = 20,
    ranking: str = "bm25",
    bm25_k1: float = 1.2,
    bm25_b: float = 0.75,
) -> dict[str, Any]:
    from .email_corpus import search_email_graphrag_duckdb

    return search_email_graphrag_duckdb(
        index_path=index_path,
        query=query,
        limit=limit,
        ranking=ranking,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
    )


async def import_gmail_workspace_evidence(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .email_import import import_gmail_evidence

    return await import_gmail_evidence(*args, **kwargs)


async def run_gmail_workspace_duckdb_pipeline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .email_pipeline import run_gmail_duckdb_pipeline

    return await run_gmail_duckdb_pipeline(*args, **kwargs)


@dataclass(frozen=True)
class EmailCorpusPaths:
    manifest_path: Path
    graphrag_dir: Path
    duckdb_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "manifest_path": str(self.manifest_path),
            "graphrag_dir": str(self.graphrag_dir),
            "duckdb_path": str(self.duckdb_path),
        }


def canonical_email_corpus_paths(
    *,
    repo_root: str | Path,
    case_slug: str,
) -> EmailCorpusPaths:
    root = Path(repo_root).expanduser().resolve()
    import_dir = root / "evidence" / "email_imports" / case_slug
    graphrag_dir = import_dir / "graphrag"
    return EmailCorpusPaths(
        manifest_path=import_dir / "email_import_manifest.json",
        graphrag_dir=graphrag_dir,
        duckdb_path=graphrag_dir / "duckdb" / "email_search.duckdb",
    )


__all__ = [
    "EmailCorpusPaths",
    "build_complaint_terms",
    "build_email_workspace_corpus",
    "canonical_email_corpus_paths",
    "import_gmail_workspace_evidence",
    "import_local_eml_directory",
    "merge_email_manifests",
    "run_gmail_workspace_duckdb_pipeline",
    "save_email_bundle",
    "score_email_relevance",
    "search_email_workspace_corpus",
]
