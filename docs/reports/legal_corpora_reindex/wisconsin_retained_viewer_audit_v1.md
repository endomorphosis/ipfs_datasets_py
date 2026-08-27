# Wisconsin retained-viewer audit v1

Audit date: 2026-08-26

Scope: read-only reconciliation of the Wisconsin Legislature sliding-viewer
route, historical fetch-cache objects, normalized derivatives, and the current
strict Wisconsin parser. No network acquisition was launched and no retained
evidence or acquisition artifact was changed.

## Source-derived hierarchy

The retained official root response at
`https://docs.legis.wisconsin.gov/statutes/statutes` is 317,921 bytes with
SHA-256
`66bcea27111f5dc7aa81c5ff0a2486b2a5268268829b36b01561274eac1c5da8`.
It exposes exactly 470 unique numeric chapters, in source order from chapter 1
through chapter 995. This 470-row source frontier is authoritative for the
strict route; the older 480-row repaired catalog is a normalized synthetic
catalog and is not official viewer HTML.

The 470 retained initial chapter windows expose 13,396 unique leading TOC
section identities. Of those chapter windows, 131 expose a first source-bound
`Down` continuation. No chapter continuation window was retained, so the final
section-locator cardinality and any later chapter-continuation URLs remain
unknown until acquisition. The exact hierarchy is therefore:

1. one official root;
2. 470 source-listed chapter viewer pages;
3. source-derived chapter continuation waves until each chapter body begins or
   is typed terminal;
4. the complete source-ordered cross-chapter section union; and
5. source-derived section continuation waves until every section is operative
   or typed terminal.

The known lower-bound frontier contains 14,832 distinct URLs: the root, 470
initial chapters, 13,396 initial sections, 131 known first chapter
continuations, and 834 known first section continuations. Later continuations
and additional section locators discovered from them are intentionally not
guessed.

## Historical parser inputs and exact residuals

The largest historical Wisconsin fetch cache contains 14,337 unique URLs and
14,337 unique content digests totaling 1,402,013,000 declared bytes. Its URL
classes are one root, 470 chapter HTML pages, 470 redundant chapter PDFs, and
13,396 section HTML pages. All were recorded as `requests_direct`, and all
recorded size and SHA-256 values match their bodies.

Those cache records contain only `cached_at`, `provider`, `sha256`, `size`,
`state_code`, and `url`. They contain no authorizing transport receipt,
sanitized request, response status/headers, or retained parser-input envelope.
Consequently, zero historical cache objects are admissible for strict
ledger-only replay. They are useful offline parser fixtures, but they cannot be
silently promoted into publication evidence.

The historical section URL set differs from the initial source-derived TOC set
by one row in each direction. Section 854.30 is source-listed but its TOC
self-link is omitted and its HTML body was not cached. Section 344.579 was
cached after legacy citation-link traversal but is not an initial-window TOC
row; it must not become a frontier member unless a retained chapter
continuation discovers it. The local chapter 854 PDF, SHA-256
`f4694918a3f49e8358a105f9fc7bbb4ea47b92d4244d780b2aad1bb5a9101146`,
confirms that section 854.30 is operative, but the PDF is not a substitute for
the exact HTML-route parser input.

Because no admissible Wisconsin ledger inputs exist, the strict acquisition
residual is the entire eventually discovered viewer frontier. Within the known
lower bound, every one of the 14,832 URLs is residual for certification. All
131 first chapter continuations and all 834 first section continuations are
also absent from the historical fetch cache.

## Current offline classification

Eight former chapter-parser residuals were false positives. Seven TOC titles
contained citations to other sections, and the old parser counted those title
citations as competing self-links. The eighth was the unlinked but exact
source row for section 854.30. Leading TOC identity now controls the row, while
later title links remain citations.

Of the 13,395 source-listed initial section bodies present in the cache, 12,561
are already complete operative sections and 834 require a first continuation.
Nine of the operative rows contain short but complete one-sentence laws; they
are no longer rejected by an arbitrary 40-character floor. No source-listed
initial chapter or completed initial section is typed terminal in this
snapshot. Terminal counts for the complete corpus remain unknown until the
continuation graph closes, and the strict parser does not infer them.

The prior full normalized derivative contains 12,894 unique section identities
and the smaller published derivative contains 160. Neither is a parser-input
ledger, neither closes the current continuation graph, and neither is reused
as source evidence.

## Nonduplication and prepared acquisition policy

Two earlier Wisconsin caches contain 5,014 and 6,085 URLs. Both are complete
URL subsets of the 14,337-object cache. Against the largest cache, 5,013 of
5,014 and 6,084 of 6,085 common URLs have the same content digest; one response
in each earlier run changed. Selecting a single latest endpoint map for audit
avoids ingesting repeated bodies, while content identity prevents the changed
responses from being conflated.

The strict unbounded path now performs one bounded, direct-preferred root wave,
then submits each currently known descendant/body wave as one deterministic
source-ordered same-domain plural request. Each plural request uses one Common
Crawl domain inventory plan with grouped/coalesced WARC range reuse and plural
Wayback prefix discovery. Retries contain only unresolved rows and explicitly
disable repeated grouped archive inventory. There is no per-page archive loop.
Certification replays only the complete attached acquisition ledger and makes
zero network requests. Bounded `max_statutes` probes retain their existing
behavior.

Publication remains blocked on running and closing the exact acquisition; this
audit and implementation preparation do not claim that the unknown
continuation frontier has already been acquired or classified.
