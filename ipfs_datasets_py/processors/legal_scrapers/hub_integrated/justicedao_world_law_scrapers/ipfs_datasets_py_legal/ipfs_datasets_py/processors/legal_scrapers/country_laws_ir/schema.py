"""Fail-closed schema mapping for endomorphosis/ipfs_*_laws parquet tables.

Verified 2026-09-03 against Malta (pilot) and Germany (column-drift check):

Laws columns (both countries):
  id, title, text, source_url, source_type, jurisdiction, country, language,
  eli, date, date_issued, retrieved_at, license, law_status, identifier,
  official_identifier, article_count, json_path, metadata_json

Drift: Malta article_count is int64; Germany article_count is int32.
       Germany eli is frequently null. Neither is a missing identifier.

Articles columns (both countries; Malta snapshot has 0 rows):
  law_id, id, title, text, source_url, document_number, article_number,
  record_type, metadata_json

Required identity columns are NOT invented. Missing required identifiers
fail the build.
"""

from __future__ import annotations

REQUIRED_LAW_COLUMNS = ("id", "title", "text")
REQUIRED_ARTICLE_COLUMNS = ("id", "law_id", "title", "text")

OPTIONAL_LAW_COLUMNS = (
    "source_url",
    "source_type",
    "jurisdiction",
    "country",
    "language",
    "eli",
    "date",
    "date_issued",
    "retrieved_at",
    "license",
    "law_status",
    "identifier",
    "official_identifier",
    "article_count",
    "json_path",
    "metadata_json",
)

OPTIONAL_ARTICLE_COLUMNS = (
    "source_url",
    "document_number",
    "article_number",
    "record_type",
    "metadata_json",
)

# Canonical field mapping used in the CID-keyed corpus.
LAW_FIELD_MAP = {
    "source_id": "id",
    "title": "title",
    "body": "text",
    "source_url": "source_url",
    "source_type": "source_type",
    "jurisdiction": "jurisdiction",
    "country": "country",
    "language": "language",
    "eli": "eli",
    "date": "date",
    "date_issued": "date_issued",
    "retrieved_at": "retrieved_at",
    "license_expression": "license",
    "law_status": "law_status",
    "identifier": "identifier",
    "official_identifier": "official_identifier",
    "article_count": "article_count",
    "metadata_json": "metadata_json",
}

ARTICLE_FIELD_MAP = {
    "source_id": "id",
    "law_id": "law_id",
    "title": "title",
    "body": "text",
    "source_url": "source_url",
    "document_number": "document_number",
    "article_number": "article_number",
    "record_type_src": "record_type",
    "metadata_json": "metadata_json",
}


class SchemaError(ValueError):
    pass


def _cols(df) -> set[str]:
    return set(map(str, df.columns))


def validate_laws(df) -> None:
    missing = [c for c in REQUIRED_LAW_COLUMNS if c not in _cols(df)]
    if missing:
        raise SchemaError(
            f"laws.parquet missing required identifier/content columns {missing}; "
            f"present={sorted(_cols(df))}. Fail closed — will not invent ids."
        )
    null_ids = int(df["id"].isna().sum()) if "id" in df.columns else len(df)
    empty_ids = int((df["id"].astype(str).str.strip() == "").sum()) if "id" in df.columns else 0
    if null_ids or empty_ids:
        raise SchemaError(
            f"laws.parquet has {null_ids} null and {empty_ids} empty id values. Fail closed."
        )


def validate_articles(df) -> None:
    if df is None or df.empty:
        return
    missing = [c for c in REQUIRED_ARTICLE_COLUMNS if c not in _cols(df)]
    if missing:
        raise SchemaError(
            f"articles.parquet missing required identifier/content columns {missing}; "
            f"present={sorted(_cols(df))}. Fail closed — will not invent ids."
        )
    null_ids = int(df["id"].isna().sum())
    null_law = int(df["law_id"].isna().sum())
    empty_ids = int((df["id"].astype(str).str.strip() == "").sum())
    empty_law = int((df["law_id"].astype(str).str.strip() == "").sum())
    if null_ids or empty_ids or null_law or empty_law:
        raise SchemaError(
            f"articles.parquet has null/empty identifiers "
            f"(id null={null_ids} empty={empty_ids}; law_id null={null_law} empty={empty_law}). Fail closed."
        )
