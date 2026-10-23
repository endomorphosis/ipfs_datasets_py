"""Shared normalization library for the world municipal-law harvester fleet.

Modules:
- :mod:`schema` — the 19-column generalized schema + fail-closed validation.
- :mod:`jurisdiction` — jurisdiction-ID abstraction (TERYT, INE, DICOFRE,
  CBS, NLIC MST, LAU, GNIS).
- :mod:`normalize` — row builders reusing the hub lane's CID/strip_tags.
- :mod:`parquet_io` — ZSTD/snappy parquet read/write + validation sidecars.
- :mod:`catalog` — country coverage manifest (the fleet's country registry).
- :mod:`text_quality` — extraction-usability gate (control-char ratio,
  ``(cid:`` density, letter share): failed extractions count as NOT
  extracted, so builders fall through to OCR or defer the document.

All modules are import-light (stdlib + pyarrow only). The hub lane's
``cid_v1_raw_sha256``/``strip_tags`` are loaded by file path so importing
this package never triggers ``legal_scrapers/__init__``'s heavy surface.
"""

from __future__ import annotations

from . import catalog, jurisdiction, normalize, parquet_io, schema, text_quality
from .catalog import COUNTRIES, get_country, iter_countries, set_status
from .jurisdiction import (
    SCHEMES,
    JurisdictionScheme,
    get_scheme,
    jurisdiction_file_name,
    normalize_jurisdiction_id,
)
from .normalize import (
    assign_doc_order,
    chunk_content,
    chunk_title,
    cid_v1_raw_sha256,
    drop_empty_rows,
    ensure_unique_doc_ids,
    finalize_rows,
    make_cid,
    make_row,
    slugify,
    strip_tags,
)
from .parquet_io import (
    default_compression,
    read_html_parquet,
    write_html_parquet,
    write_validation_report,
)
from .schema import (
    EXPECTED_COLUMNS,
    assert_valid,
    build_schema,
    rows_to_table,
    validate_table,
    validation_report,
)
from .text_quality import (
    assert_usable_text,
    cid_token_count,
    first_usable_extraction,
    garble_ratio,
    is_usable_text,
    letter_share,
    usability_failures,
)

__all__ = [
    "catalog",
    "jurisdiction",
    "normalize",
    "parquet_io",
    "schema",
    "text_quality",
    "COUNTRIES",
    "get_country",
    "iter_countries",
    "set_status",
    "SCHEMES",
    "JurisdictionScheme",
    "get_scheme",
    "jurisdiction_file_name",
    "normalize_jurisdiction_id",
    "assign_doc_order",
    "chunk_content",
    "chunk_title",
    "cid_v1_raw_sha256",
    "drop_empty_rows",
    "ensure_unique_doc_ids",
    "finalize_rows",
    "make_cid",
    "make_row",
    "slugify",
    "strip_tags",
    "default_compression",
    "read_html_parquet",
    "write_html_parquet",
    "write_validation_report",
    "EXPECTED_COLUMNS",
    "assert_valid",
    "build_schema",
    "rows_to_table",
    "validate_table",
    "validation_report",
    "assert_usable_text",
    "cid_token_count",
    "first_usable_extraction",
    "garble_ratio",
    "is_usable_text",
    "letter_share",
    "usability_failures",
]
