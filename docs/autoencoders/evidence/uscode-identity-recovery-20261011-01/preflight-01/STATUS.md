# US Code archive identity recovery

This follow-up investigates the **378,935 unresolved archived IDs** left by the
accepted complete source scan. The parent scan still accounts for **3,840,988
source occurrences**, including **64,969 exact archived ID/hash/legal-ID joins**.
The parent evidence, source bytes, progress ledger, embeddings and checkpoints
remain unchanged. This campaign does not relabel unresolved IDs or train a model.

The [campaign manifest](campaign.json) binds the published parent and its
independent reviews. The [run plan](run-plan.json) specifies the proposed bounded
metadata-only ordinal diagnosis. Its execution and result review are pending.

## Available producer evidence

The [local recipe survey](review/local-recipe-survey.json) reproduces the archived
compiler digest `sha256:05ded12711ebac48224f6f86035701022b35745c0b18242c3903deca6b8ad0c1`
from seven compiler/parser/decompiler blobs in datasets commit
`9422f1835f6ad8ef1bd14414effb5ae9d4fe0895`. Those digest scopes exclude the
ingestion, source loader, sentence splitter and identity generator. They identify
available compiler components; they do not authenticate the original ingestion
launch or encoder input.

That available ingestion snapshot invokes `inventory_uscode_documents([document])`
for each document while buffering 64 documents for commits. Its identity ordinal
therefore resets per document. The later source census reconstructs ordinals
across groups of 64 valid documents. The two counters define different IDs for
many otherwise identical source bindings. The original producer launch remains
unrecovered, so the per-document counter is a hypothesis to test rather than an
approved historical alias recipe.

The [pinned Hub survey](review/remote-producer-survey.json) verifies that remote
queue/source LFS identities match the original frozen assets. Historical report
manifests bind later diagnostic runners and the same source/queue bytes; they
do not supply the initial extraction-owner map or launch. Parallel checkpoint
inventory work remains with its existing owner.

## Recorded-hash comparison

The [metadata and resource survey](review/identity-pilot-resource-survey.json)
finds that all **443,904** archived span rows have nonblank legal IDs and valid
64-hex source hashes. Missing identity columns do not explain this population.
Against the **64,969 retained targets**, **3,700 unresolved archived rows** share
a recorded legal ID and normalized text hash: **1,192** match one retained
physical occurrence and **2,508** match multiple retained occurrences.

This extends the earlier zero-match comparison against the smaller 18,342-row
seed. Singleton status applies only within the retained target subset; the
3,776,019 outside-target occurrences lack a complete persisted identity index.
Repeated short fragments remain in the denominator and are not semantic gold.
A content hash alone cannot establish the correct physical location or original
encoder context.

## Bounded ordinal diagnosis

First authenticate the stopped database, report, manifest, original progress and
completed independent parent review. Reproduce **every** retained baseline ID
using its declared citation, CID, legal reference, normalized text hash, title,
section, query, release/schema, unit ID and historical ordinal. Refuse the
diagnosis if any baseline binding fails. Only then replace the ordinal with the
stored section-local ordinal and compare the hypothetical ID against unresolved
archive rows on **complete ID + source SHA-256 + legal ID**.

Keep candidate links separate from approved aliases. Report physical matches,
distinct archived IDs and ambiguity within retained targets independently.
Full-source uniqueness, actual producer launch, encoder context, compatible
embedding reuse, semantic reconstruction, teacher qualification and proof
authority remain unqualified. Neither original IDs nor parent receipts are
rewritten.

The [reused guardian](guard-reuse.json) changes only the runtime campaign path.
Admission requests one CPU/child slot, 768 MB outer memory and 16 MiB outer
storage. The diagnostic uses 256 MB DuckDB memory, one thread and no spill;
limits include 65,536 retained rows, 500,000 archive rows, 8 MiB output, a 2 MiB
report, 32 examples and a 300-second outer deadline. A fresh named-root resource
census is required; the older 674,809,450-byte headroom estimate is not admission.
The exact existing scheduler is adopted without a capacity reset or foreign
claim release. Enforcement remains cooperative and sampled.

## Remaining source and reconstruction work

An accepted positive diagnostic can support the next explicitly reviewed
source-profile experiment. It cannot resolve all 378,935 IDs from this subset.
An accepted negative diagnostic cannot establish absence from unindexed source
occurrences. Recover producer launch and extraction custody, then measure and
admit complete source identity shards before whole-source uniqueness claims.

The available historical cache also truncates stored text at 32,768 characters
while retaining the caller's ID. This is a possible full-text/stored-hash
difference to test separately, not an established cause of unresolved IDs or
the 1,654 historical count difference. Changing only an ordinal changes IDs,
not sentence counts.

After source binding, retain separate LegalIR, CodebaseIR, SecurityIR and IntentIR
cells at 8D, 384D and 768D, with schema/version, decoder task and producer/context
profile separation. Reuse compatible original assets and the preserved warm
state. Measure generated semantic IR fidelity and learned
`legal text -> LegalIR -> legal text` reconstruction separately from raw-byte
restoration, logic projection and actual proof checks.
