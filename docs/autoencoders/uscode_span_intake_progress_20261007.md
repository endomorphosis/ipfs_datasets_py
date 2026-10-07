# US Code span intake: implementation and measured progress

This implements the first intake slice of the [all-span processing plan](uscode_all_span_processing_plan_20261007.md), reusing immutable original sources and archived assets. It adds no trained model, replacement embedding or proof claim.

## Implemented and checked

The resumable feed discovers legacy exchanges and paired-v1/v2 bundles. It preserves complete source, source release, compiler/capture fields and content-bound artifact references. Diagnostic vectors remain observations, with no injection into encoder inputs. A one-time discovery migration preserves pending revisions and acknowledged bundles. Downloads, Arrow expansion, artifact expansion and delivered observations have explicit bounds. Records are returned only after the durable ready transaction commits; four injected UPDATE/COMMIT failure controls verify refusal and retry.

SpanCache preserves complete source and decoder text on new local writes. Default limits are 1,048,576 UTF-8 bytes per field, 67,108,864 text bytes per write batch and 4,096 write rows. It checks the actual write set and declared source hashes before changing rows, compiler invalidation or claims. Historical text/hash records and advisory remote progress remain intact.

The new local census uses one DuckDB writer, immutable input/code/tokenizer pins, physical source-occurrence identities and transactional rows/counts/cursor updates. Unmatched, conflicting and invalid identities remain explicit. Original queue indexes are TEMP; default exports contain compact counts. Original section bytes stay in the pinned Parquet; extraction hashes historical normalized sentence bytes.

The combined cache/feed/exchange/paired/census regression run passed **335 tests**. Two additional supervisor integration failures reproduced with the original module in the same standalone dependency context; their baseline receipts are retained. Neither failure exercises the changed intake path.

## Verified inputs and bounded recovery

Cache snapshot: `justicedao/uscode-autoformal-span-cache@765176c6db79ba65c1697c21dead43666350b730`. The original resume export is 52,701,179 bytes, fully downloaded and verified against SHA-256 `7707c001d650876717651a38e442d1522c5bdab6c792539414973922af1c1d03`. It contains one metadata row and **443,904 distinct span IDs**: 22,379 sealed and 421,525 gap records. These are archived cache states; learned reconstruction and proof results require their own evidence.

The existing source `justicedao/ipfs_uscode@5016b86a273ce5e4ffd066c5ae9f5fe494dd417e` was reused and reauthenticated. Its Parquet has 60,077 physical records. The single row group's all-column decoded metadata is 1,170,039,502 bytes; selected intake columns total 330,347,299 decoded bytes. Footer totals do not establish resident memory.

The first real run committed **112 sections and 9,748 occurrences**, then refused a later sixteen-section batch at the configured span/byte limit. Its initial report remained a sixteen-section snapshot, so the stopped database was the authoritative cursor. The failed attempt and evidence were preserved; only its own stopped, durable resource claim was released after audit.

A fresh process cloned that stopped generation with unchanged input/code/bounds pins and resumed one section at a time. It reached **128 sections and 18,342 occurrences**:

| Accounting item | Measured count |
|---|---:|
| Exact archived ID + source hash + legal ID joins | 2,165 |
| Explicit unlisted regenerated occurrences | 16,177 |
| Archived IDs awaiting remaining source scanning | 441,739 |
| Retained prefix occurrences | 9,748 |
| Newly committed occurrences | 8,594 |

An independent replay reconstructed every stored occurrence and verified the prefix, hashes, ordinals, lengths and absence of skipped/duplicate occurrences. **31 independent checks passed.** The resumed attempt occupied 8,701,600 bytes within its 64,000,000-byte reservation. Both process groups stopped and both claims released. Lease observations were sampled and healthy; actual peak RSS was not established. Token counts remain null because no tokenizer was configured. `complete_source_scan` remains **false**.

## Corpus scope and historical identity

The exported 443,904 rows are separate from the underlying source inventory. The current exporter includes sealed/gap rows and omits pending rows; current `pending` statistics count all unsealed rows, including gaps. **If the archived producer used those semantics**, its counters imply 3,842,642 underlying inventory rows and 3,398,738 unexported rows. This is a conditional inference, not an authenticated full census. Absence from the export alone does not classify an occurrence as new text, missing work, a duplicate or identity drift.

The historical 64-valid-document ordinal rule remains evidence-supported for this archive. Per-document rehashing lost 1,102 exact joins and gained none. On the first 64 source documents, full-text historical replay produced 651 exact joins; 32,768-character clipping produced 264, losing 387 and gaining none. Smaller clipping limits performed worse. The current ingestion worker uses per-document ordinals, so comparisons with this archive need a separate extraction/generation identity. Neither the current worker nor a clipping hypothesis should rewrite archived IDs.

The original 443,904-row three-width float32 floor is 2,059,714,560 bytes. For the conditional 3,842,642-row inventory it would be 17,829,858,880 bytes before clauses, contexts, indexes, replicas or decoder outputs. This does not establish the final row count, require fresh encoding of every row or grant storage admission.

## Remaining gates in the comprehensive plan

1. Complete source/export reconciliation with measured storage, bounded shards or a declared archived-target scope. Account for every archived record and preserve full-source occurrences and aliases. Begin with one-section batches. A section exceeding the bound needs an explicit pending disposition or a reviewed streaming extractor.
2. Reconcile the 611 paired-v1 manifests and compiler/modal evidence against canonical sources. Descriptor closure is verified; bounded table-body and source-ID validation remains. Preserve original assets, producer conditioning and the legacy mock 8D lane's diagnostic status.
3. Build native cache routing keyed by family, dimension, schema/version, decoder task, encoder revision, context profile and checkpoint. Reuse authenticated embeddings and weights. Keep CodebaseIR, SecurityIR, LegalIR and IntentIR inventories/catalogs/model repositories separate, with parallel 8D/384D/768D paths and explicit references to shared source/CAS bytes.
4. Measure actual tokenizer lengths/truncation, then run source-only pilots with eligible learned checkpoints. Keep semantic-IR equality, legal-text byte equality, logic checks and source-bound proofs separate. The retained multilingual producer's 512-token ceiling is separate from its base model's 8,192-token capacity.
5. Warm the 768D decoder from matched learned 8D/384D teacher pairs, retaining separate heads/checkpoints for each IR schema/task. Gold selection, leakage groups and unexposed evaluation precede new training. Compiler observations and mock embeddings do not become learned teacher outputs.

This contribution completes the first intake implementation and a bounded recovery demonstration. It reports no all-source census completion, semantic reconstruction improvement, training completion or formal proof completion.

Compact receipts: [intake evidence index](evidence/uscode-span-intake-20261007/index.json).
