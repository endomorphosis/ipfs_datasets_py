# Paired US Code feed compatibility

The span feed now discovers legacy exchange manifests and paired-v1/v2
manifests in one bounded, pinned `autoformal/uscode` tree scan. Previously its
listing and download whitelist covered only legacy exchanges, so current paired
observations could not reach the durable inbox. Existing exchange producers also
use `census-v3` and `census-v4`; these now route through their matching manifest
schemas instead of being rejected by the older census-only path check.

`SpanCacheFeed.poll_once()` retains the original at-least-once delivery contract.
Discovery inserts every page's manifest descriptors and advances its cursor in
one transaction. Failed downloads or validations remain pending at their original
immutable revision. Ready bundles repeat across restarts and offline discovery
until their exact fingerprint is explicitly acknowledged. Acknowledgement means
downstream retention, not training, source admission or model promotion.

An exact prior `span-cache-incremental-feed/v1` configuration upgrades to v2 under
the existing local owner lock. The one-time migration preserves every inbox row,
status, pending revision and acknowledgement, and rewinds only discovery at its
previous pinned revision. This allows a formerly completed legacy-only scan to
discover paired namespaces. Changed repository, revision, artifact root or shard
settings still require a separate state database; foreign tables remain refused.

Paired transport validates manifest content identity, repository/path, sanitized
producer namespace, schema version, all three table kinds, filenames, sizes and
content digests before table downloads. The existing paired loader remains the
owner of typed schemas, exact source/observation hashes, comparison evidence,
learned-capture receipts, artifact decompression and reciprocal goal links.
Additional feed preflight bounds aggregate Arrow allocation and declared artifact
expansion before full loading. Returned JSON observations also count against the
ready-input budget. These are input-byte controls, not measured process-memory
limits. Filesystem aliases and manifest redirects to model weights are refused.

Paired source records retain exact UTF-8 text, the recorded source release,
complete model/compiler/comparison/provenance fields, original goal rows and
content-bound artifact-table references. Their identifiers include the recorded
source release. Legacy observations that lack that release remain separate until
an independent corpus inventory resolves their source aliases. Repeated paired
observations of the same source generation deduplicate the source record while
preserving every observation. Shards assign the source consistently.

Diagnostic raw/projected vectors remain in their original observation fields;
they are never inserted into `sample.embedding_vector`. Every paired record
continues to declare source authority, training qualification and proof authority
false. Original compiler outputs and caller-supplied diagnostic formula origins
are not relabeled as learned outputs. The feed downloads no weights, executes no
encoder/decoder, imports no supervisor task and trains no model.

Validation used real local Arrow/Parquet bundles and isolated DuckDB owners with
an inert remote transport. All 76 tests passed: the existing 29 legacy-feed
controls and 47 paired-feed controls. They cover both paired schemas, actual v2
exporter namespace normalization, source and producer corruption, forged capture
references, deferred capability goals, mixed-schema discovery, moving heads,
restart/acknowledgement, aggregate limits, table tampering, migration, path aliases
and source text exceeding 32 KiB with Unicode.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/unit/logic/test_span_cache_feed.py \
  tests/unit/logic/test_span_cache_paired_feed.py --disable-warnings
```

This closes the paired inbox interface work item. It does not complete the corpus
census, qualify the arbitrary native-cache reader, remove truncation in the
separate legacy span cache, schedule the corpus, or establish legal semantics or
proof admission. Those remain separately tracked processing-plan milestones.
