# Wallet Tools

Thin MCP wrappers around `ipfs_datasets_py.wallet` for wallet creation,
encrypted record ingestion, proof generation, document analysis, and analytics
workflows.

These tools persist state using the same local snapshot/blob layout as
`ipfs_datasets_py.wallet.cli`.

Document analysis tools keep plaintext inside the wallet service boundary.
`wallet_extract_document_text_redacted` uses the package attachment text
extractor for text/PDF/image/OCR-capable documents and returns only redacted
text plus extraction metadata. `wallet_analyze_document_form_redacted` uses the
package PDF form analyzer when possible and otherwise infers form-like fields
from redacted extracted text, returning only field metadata and form stats.
`wallet_analyze_document_redacted` returns a redacted derived summary, and
`wallet_create_document_vector_profile` returns only safe profile metadata such
as category counts and redacted per-chunk feature-signature hashes while
storing the artifact encrypted.
`wallet_analyze_documents_redacted` performs cross-record document analysis only
over authorized record IDs and returns aggregate-safe need categories, redaction
counts, and per-record derived facts without document text.
`wallet_create_redacted_graphrag` creates a redacted GraphRAG artifact from
authorized wallet documents by collapsing extracted entities to entity-type
counts and graph edges over record, need-category, redaction-type, and
entity-type nodes.
`wallet_create_record_grant`, `wallet_issue_record_invocation`, and
`wallet_decrypt_document` expose bounded UCAN record-sharing flows while
preserving the same caveat, user-presence, and revocation checks as the wallet
service. `wallet_create_export_grant`, `wallet_issue_export_invocation`,
`wallet_create_export_bundle`, `wallet_verify_export_bundle`,
`wallet_import_export_bundle`, and `wallet_export_bundle_storage` expose
encrypted export workflows without returning plaintext.
