from __future__ import annotations

import json
import math
import re
from collections import Counter
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import duckdb

from .attachment_text_extractor import extract_attachment_text


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]*")
SUBJECT_WEIGHT = 4.0
HEADER_WEIGHT = 2.0
BODY_WEIGHT = 1.0
ATTACHMENT_WEIGHT = 1.5


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokenize(value: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(str(value or "").lower())]


def _body_from_eml(eml_path: Path) -> str:
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


def _attachment_text_blocks(attachment_paths: list[str], *, include_attachment_text: bool) -> tuple[list[str], list[str]]:
    filenames: list[str] = []
    texts: list[str] = []
    for raw_path in attachment_paths:
        path = Path(str(raw_path or "")).expanduser().resolve()
        filenames.append(path.name)
        if not include_attachment_text:
            continue
        extraction = extract_attachment_text(path, use_ocr=True)
        text = _normalize_text(str(extraction.get("text") or ""))
        if text:
            texts.append(text)
    return filenames, texts


def _record_bundle_dir(record: dict[str, Any], manifest_path: Path) -> Path | None:
    raw = str(record.get("bundle_dir") or "").strip()
    if not raw or raw == ".":
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def _record_eml_path(record: dict[str, Any], manifest_path: Path) -> Path | None:
    raw = str(record.get("eml_path") or record.get("email_path") or "").strip()
    if raw and raw != ".":
        path = Path(raw)
        if not path.is_absolute():
            path = manifest_path.parent / path
        return path.resolve()
    bundle_dir = _record_bundle_dir(record, manifest_path)
    if bundle_dir is None:
        return None
    return (bundle_dir / "message.eml").resolve()


def _snippet_from_text(full_text: str, query_terms: list[str], *, max_chars: int = 240) -> str:
    clean_text = _normalize_text(full_text)
    if not clean_text:
        return ""
    lowered = clean_text.lower()
    positions = [lowered.find(term) for term in query_terms if term and lowered.find(term) >= 0]
    if not positions:
        return clean_text[:max_chars]
    start = max(0, min(positions) - 60)
    end = min(len(clean_text), start + max_chars)
    return clean_text[start:end]


def _message_row(record: dict[str, Any], manifest_path: Path, *, include_attachment_text: bool) -> dict[str, Any]:
    eml_path = _record_eml_path(record, manifest_path)
    body_text = _body_from_eml(eml_path) if eml_path else ""
    attachment_paths = [str(path or "") for path in list(record.get("attachment_paths") or [])]
    attachment_filenames, attachment_texts = _attachment_text_blocks(
        attachment_paths,
        include_attachment_text=include_attachment_text,
    )

    subject = str(record.get("subject") or "")
    from_value = str(record.get("from") or "")
    to_value = str(record.get("to") or "")
    cc_value = str(record.get("cc") or "")
    participants = [str(item or "").strip().lower() for item in list(record.get("participants") or []) if str(item or "").strip()]
    attachment_text = "\n\n".join(text for text in attachment_texts if text)

    full_text_parts = [
        f"Subject: {subject}",
        f"From: {from_value}",
        f"To: {to_value}",
        f"Cc: {cc_value}",
        f"Participants: {', '.join(participants)}" if participants else "",
        body_text,
        "\n".join(f"Attachment filename: {name}" for name in attachment_filenames if name),
        attachment_text,
    ]
    full_text = "\n".join(part for part in full_text_parts if part).strip()

    subject_tokens = _tokenize(subject)
    header_tokens = _tokenize(" ".join([from_value, to_value, cc_value, " ".join(participants)]))
    body_tokens = _tokenize(body_text)
    attachment_tokens = _tokenize(" ".join(attachment_filenames) + "\n" + attachment_text)

    weighted_counts: Counter[str] = Counter()
    for token in subject_tokens:
        weighted_counts[token] += SUBJECT_WEIGHT
    for token in header_tokens:
        weighted_counts[token] += HEADER_WEIGHT
    for token in body_tokens:
        weighted_counts[token] += BODY_WEIGHT
    for token in attachment_tokens:
        weighted_counts[token] += ATTACHMENT_WEIGHT

    message_key = str(record.get("message_id_header") or "") or str(record.get("raw_sha256") or "") or str(record.get("date") or "")
    return {
        "message_key": message_key,
        "message_id_header": str(record.get("message_id_header") or ""),
        "subject": subject,
        "from": from_value,
        "to": to_value,
        "cc": cc_value,
        "date": str(record.get("date") or ""),
        "participants_json": json.dumps(participants, ensure_ascii=False),
        "bundle_dir": str(record.get("bundle_dir") or ""),
        "eml_path": str(eml_path) if eml_path else "",
        "attachment_paths_json": json.dumps(attachment_paths, ensure_ascii=False),
        "attachment_filenames_json": json.dumps(attachment_filenames, ensure_ascii=False),
        "body_text": body_text,
        "attachment_text": attachment_text,
        "full_text": full_text,
        "doc_length": float(sum(weighted_counts.values())),
        "weighted_terms": weighted_counts,
    }


def _load_message_rows(manifest_path: Path, *, include_attachment_text: bool) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in list(manifest.get("emails") or []):
        row = _message_row(record, manifest_path, include_attachment_text=include_attachment_text)
        if row["message_key"] in seen:
            continue
        seen.add(row["message_key"])
        rows.append(row)
    return rows


def _build_term_rows(message_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not message_rows:
        return [], []
    document_count = len(message_rows)
    document_frequency: Counter[str] = Counter()
    for row in message_rows:
        document_frequency.update(set(row["weighted_terms"].keys()))

    average_doc_length = (
        sum(float(row["doc_length"] or 0.0) for row in message_rows) / document_count
        if document_count
        else 0.0
    )
    term_rows: list[dict[str, Any]] = []
    bm25_rows: list[dict[str, Any]] = []
    for row in message_rows:
        for term, weighted_tf in sorted(row["weighted_terms"].items()):
            weighted_tf_value = float(weighted_tf)
            df = int(document_frequency.get(term) or 0)
            idf = math.log(((document_count - df + 0.5) / (df + 0.5)) + 1.0) if df else 0.0
            term_rows.append(
                {
                    "message_key": row["message_key"],
                    "term": term,
                    "weighted_tf": weighted_tf_value,
                }
            )
            bm25_rows.append(
                {
                    "message_key": row["message_key"],
                    "term": term,
                    "tf": weighted_tf_value,
                    "df": df,
                    "idf": idf,
                    "doc_length": float(row["doc_length"] or 0.0),
                    "avg_doc_length": average_doc_length,
                    "document_count": document_count,
                }
            )
    return term_rows, bm25_rows


def _write_duckdb_index(
    *,
    message_rows: list[dict[str, Any]],
    term_rows: list[dict[str, Any]],
    bm25_rows: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    duckdb_path = output_dir / "email_search.duckdb"
    messages_parquet_path = output_dir / "email_messages.parquet"
    terms_parquet_path = output_dir / "email_terms.parquet"
    bm25_terms_parquet_path = output_dir / "email_bm25_terms.parquet"

    con = duckdb.connect(str(duckdb_path))
    try:
        con.execute("DROP TABLE IF EXISTS email_messages")
        con.execute("DROP TABLE IF EXISTS email_terms")
        con.execute("DROP TABLE IF EXISTS email_bm25_documents")
        con.execute("DROP TABLE IF EXISTS email_bm25_terms")
        con.execute(
            """
            CREATE TABLE email_messages (
                message_key VARCHAR PRIMARY KEY,
                message_id_header VARCHAR,
                subject VARCHAR,
                "from" VARCHAR,
                "to" VARCHAR,
                cc VARCHAR,
                date VARCHAR,
                participants_json VARCHAR,
                bundle_dir VARCHAR,
                eml_path VARCHAR,
                attachment_paths_json VARCHAR,
                attachment_filenames_json VARCHAR,
                body_text VARCHAR,
                attachment_text VARCHAR,
                full_text VARCHAR,
                doc_length DOUBLE
            )
            """
        )
        con.executemany(
            """
            INSERT INTO email_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["message_key"],
                    row["message_id_header"],
                    row["subject"],
                    row["from"],
                    row["to"],
                    row["cc"],
                    row["date"],
                    row["participants_json"],
                    row["bundle_dir"],
                    row["eml_path"],
                    row["attachment_paths_json"],
                    row["attachment_filenames_json"],
                    row["body_text"],
                    row["attachment_text"],
                    row["full_text"],
                    row["doc_length"],
                )
                for row in message_rows
            ],
        )
        con.execute(
            """
            CREATE TABLE email_terms (
                message_key VARCHAR,
                term VARCHAR,
                weighted_tf DOUBLE
            )
            """
        )
        if term_rows:
            con.executemany(
                "INSERT INTO email_terms VALUES (?, ?, ?)",
                [(row["message_key"], row["term"], row["weighted_tf"]) for row in term_rows],
            )
        con.execute("CREATE TABLE email_bm25_documents AS SELECT message_key, doc_length FROM email_messages")
        con.execute(
            """
            CREATE TABLE email_bm25_terms (
                message_key VARCHAR,
                term VARCHAR,
                tf DOUBLE,
                df INTEGER,
                idf DOUBLE,
                doc_length DOUBLE,
                avg_doc_length DOUBLE,
                document_count INTEGER
            )
            """
        )
        if bm25_rows:
            con.executemany(
                "INSERT INTO email_bm25_terms VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        row["message_key"],
                        row["term"],
                        row["tf"],
                        row["df"],
                        row["idf"],
                        row["doc_length"],
                        row["avg_doc_length"],
                        row["document_count"],
                    )
                    for row in bm25_rows
                ],
            )

        con.execute(f"COPY email_messages TO '{messages_parquet_path}' (FORMAT PARQUET)")
        con.execute(f"COPY email_terms TO '{terms_parquet_path}' (FORMAT PARQUET)")
        con.execute(f"COPY email_bm25_terms TO '{bm25_terms_parquet_path}' (FORMAT PARQUET)")
    finally:
        con.close()

    return {
        "duckdb_path": str(duckdb_path),
        "messages_parquet_path": str(messages_parquet_path),
        "terms_parquet_path": str(terms_parquet_path),
        "bm25_terms_parquet_path": str(bm25_terms_parquet_path),
    }


def build_email_duckdb_index(
    *,
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    include_attachment_text: bool = True,
    append: bool = False,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path).expanduser().resolve()
    index_dir = Path(output_dir).expanduser().resolve() if output_dir else manifest_file.parent / "duckdb"

    message_rows = _load_message_rows(manifest_file, include_attachment_text=include_attachment_text)
    if append:
        existing_duckdb_path = index_dir / "email_search.duckdb"
        if existing_duckdb_path.exists():
            con = duckdb.connect(str(existing_duckdb_path))
            try:
                existing_rows = con.execute(
                    """
                    SELECT
                        message_key,
                        message_id_header,
                        subject,
                        "from",
                        "to",
                        cc,
                        date,
                        participants_json,
                        bundle_dir,
                        eml_path,
                        attachment_paths_json,
                        attachment_filenames_json,
                        body_text,
                        attachment_text,
                        full_text,
                        doc_length
                    FROM email_messages
                    """
                ).fetchall()
            finally:
                con.close()
            for row in existing_rows:
                message_rows.append(
                    {
                        "message_key": row[0],
                        "message_id_header": row[1],
                        "subject": row[2],
                        "from": row[3],
                        "to": row[4],
                        "cc": row[5],
                        "date": row[6],
                        "participants_json": row[7],
                        "bundle_dir": row[8],
                        "eml_path": row[9],
                        "attachment_paths_json": row[10],
                        "attachment_filenames_json": row[11],
                        "body_text": row[12],
                        "attachment_text": row[13],
                        "full_text": row[14],
                        "doc_length": row[15],
                        "weighted_terms": Counter(),
                    }
                )

    deduped_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in message_rows:
        key = str(row["message_key"] or "")
        if not key or key in seen:
            continue
        seen.add(key)
        if not row.get("weighted_terms"):
            weighted_counts: Counter[str] = Counter()
            for token in _tokenize(str(row.get("full_text") or "")):
                weighted_counts[token] += 1.0
            row["weighted_terms"] = weighted_counts
            row["doc_length"] = float(sum(weighted_counts.values()))
        deduped_rows.append(row)

    term_rows, bm25_rows = _build_term_rows(deduped_rows)
    paths = _write_duckdb_index(
        message_rows=deduped_rows,
        term_rows=term_rows,
        bm25_rows=bm25_rows,
        output_dir=index_dir,
    )
    return {
        "status": "created",
        "manifest_path": str(manifest_file),
        "output_dir": str(index_dir),
        "email_count": len(deduped_rows),
        "append_mode": bool(append),
        "include_attachment_text": bool(include_attachment_text),
        "bm25_distinct_term_count": len({row["term"] for row in bm25_rows}),
        **paths,
    }


def search_email_duckdb_index(
    *,
    index_path: str | Path,
    query: str,
    limit: int = 20,
    ranking: str = "bm25",
    bm25_k1: float = 1.2,
    bm25_b: float = 0.75,
) -> dict[str, Any]:
    duckdb_path = Path(index_path).expanduser().resolve()
    con = duckdb.connect(str(duckdb_path))
    try:
        query_terms = _tokenize(query)
        if not query_terms:
            return {"status": "success", "ranking": ranking, "query": query, "result_count": 0, "results": []}

        bm25_term_count = con.execute("SELECT COUNT(*) FROM email_bm25_terms").fetchone()[0]
        bm25_doc_count = con.execute("SELECT COUNT(*) FROM email_bm25_documents").fetchone()[0]
        effective_ranking = ranking
        if ranking == "bm25" and (bm25_term_count == 0 or bm25_doc_count == 0):
            effective_ranking = "weighted"

        if effective_ranking == "bm25":
            rows = con.execute(
                """
                SELECT
                    m.message_key,
                    m.subject,
                    m."from",
                    m."to",
                    m.cc,
                    m.date,
                    m.full_text,
                    SUM(
                        t.idf * (
                            (t.tf * (? + 1.0)) /
                            NULLIF(t.tf + (? * (1.0 - ? + (? * (t.doc_length / NULLIF(t.avg_doc_length, 0.0))))), 0.0)
                        )
                    ) AS score
                FROM email_bm25_terms t
                JOIN email_messages m ON m.message_key = t.message_key
                WHERE t.term IN ({placeholders})
                GROUP BY 1,2,3,4,5,6,7
                ORDER BY score DESC, m.date DESC
                LIMIT ?
                """.format(placeholders=",".join("?" for _ in query_terms)),
                [bm25_k1, bm25_k1, bm25_b, bm25_b, *query_terms, int(limit)],
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT
                    m.message_key,
                    m.subject,
                    m."from",
                    m."to",
                    m.cc,
                    m.date,
                    m.full_text,
                    SUM(t.weighted_tf) AS score
                FROM email_terms t
                JOIN email_messages m ON m.message_key = t.message_key
                WHERE t.term IN ({placeholders})
                GROUP BY 1,2,3,4,5,6,7
                ORDER BY score DESC, m.date DESC
                LIMIT ?
                """.format(placeholders=",".join("?" for _ in query_terms)),
                [*query_terms, int(limit)],
            ).fetchall()

        results = [
            {
                "message_key": row[0],
                "subject": row[1],
                "from": row[2],
                "to": row[3],
                "cc": row[4],
                "date": row[5],
                "score": float(row[7] or 0.0),
                "snippet": _snippet_from_text(str(row[6] or ""), query_terms),
            }
            for row in rows
        ]
        return {
            "status": "success",
            "ranking": effective_ranking,
            "query": query,
            "result_count": len(results),
            "results": results,
        }
    finally:
        con.close()


__all__ = ["build_email_duckdb_index", "search_email_duckdb_index"]
