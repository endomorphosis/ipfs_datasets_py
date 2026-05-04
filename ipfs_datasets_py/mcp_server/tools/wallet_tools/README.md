# Wallet Tools

Thin MCP wrappers around `ipfs_datasets_py.wallet` for wallet creation,
encrypted record ingestion, proof generation, document analysis, and analytics
workflows.

These tools persist state using the same local snapshot/blob layout as
`ipfs_datasets_py.wallet.cli`.

Document analysis tools keep plaintext inside the wallet service boundary.
`wallet_extract_document_text_redacted` uses the package attachment text
extractor for text/PDF/image/OCR-capable documents and returns only redacted
text plus extraction metadata. `wallet_analyze_document_redacted` returns a
redacted derived summary, and
`wallet_create_document_vector_profile` returns only safe profile metadata such
as category counts and redacted per-chunk feature-signature hashes while
storing the artifact encrypted.
`wallet_analyze_documents_redacted` performs cross-record document analysis only
over authorized record IDs and returns aggregate-safe need categories, redaction
counts, and per-record derived facts without document text.
