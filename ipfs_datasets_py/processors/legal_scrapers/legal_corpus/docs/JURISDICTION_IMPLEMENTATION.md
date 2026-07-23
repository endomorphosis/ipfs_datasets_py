# Legal Corpus Jurisdiction Implementation Guide

This framework defines the reusable legal corpus pipeline contracts used by the
Netherlands BWBR implementation. Future jurisdictions should implement the same
interfaces without weakening Netherlands behavior or reusing unofficial source
logic.

## Required Spec

Every jurisdiction must expose a `JurisdictionSpec` with:

- stable `jurisdiction_id`, `slug`, display name, country code, and language codes
- authoritative source descriptions
- default raw/catalog paths, if the jurisdiction supports durable acquisition
- Hugging Face repo ids for each published package variant
- aliases used by the registry and CLI dispatchers

## Required Components

Every production jurisdiction must provide concrete implementations for:

- `DiscoveryProvider`: official-source discovery, catalog import, queuing, and
  coverage reporting
- `FetchProvider`: resumable fetching/scraping from official source records
- `Parser`: source-document parsing into law and article records
- `HierarchyExtractor`: normalized hierarchy extraction for books, titles,
  chapters, divisions, paragraphs, articles, or local equivalents
- `StatusClassifier`: official metadata based status/version classification
- `CIDGenerator`: deterministic content-address generation for law and article
  payloads
- `PackageBuilder`: normalized and CID package builders
- `VectorIndexBuilder`: dense retrieval index builder
- `BM25IndexBuilder`: sparse retrieval index builder
- `JsonLdGraphBuilder`: JSON-LD graph builder
- `HuggingFacePublisher`: upload and remote verification
- `IntegrityValidator`: duplicate, parent/child, status inheritance, CID, and
  graph validation

## Status Semantics

Jurisdictions must preserve inactive and historical law. They must not delete a
law merely because it is old, repealed, superseded, or no longer current.

Each law row and article row should carry:

- `law_status`: one of `current`, `historical`, `repealed`, `superseded`,
  `unknown`
- `is_current`
- `valid_from`
- `valid_to`
- `effective_date`
- `retrieved_at`
- `status_source`
- `status_confidence`
- `status_note`
- version fields where available

Article rows must inherit the parent law status/version fields unless official
article-level metadata proves a different value. If official metadata cannot
determine status, use `unknown`.

## CID And Packaging Rules

CID generation must be deterministic for the exact normalized row payload. If
status/version fields are part of that payload, CID values are expected to change
when those fields change. Package manifests and all downstream indexes must be
rebuilt consistently from the same row set.

## Completeness And Integrity

Jurisdictions with durable ingestion should converge through explicit states
such as discovered, queued, downloading, downloaded, parsed, packaged, uploaded,
verified, failed, and permanently skipped. Coverage reports must distinguish
processed, remaining, transient failures, permanent failures, and intentionally
skipped identifiers.

Integrity validation should detect duplicate source identifiers, duplicate CIDs,
orphan article rows, missing parent law rows, status inheritance drift, and
broken graph edges.

## Publication

Dataset cards must state corpus scope, scrape date, exact row counts,
status-labeling semantics, limitations, and that the dataset is not legal advice.
Do not claim full jurisdiction coverage unless every discovered official
identifier has been parsed, intentionally skipped, or permanently failed with an
explanation.

## First Implementation

The Netherlands implementation lives in
`ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.jurisdiction` and
adapts the existing BWBR catalog-backed pipeline behind these interfaces. Its
existing CLI commands remain backward compatible.
