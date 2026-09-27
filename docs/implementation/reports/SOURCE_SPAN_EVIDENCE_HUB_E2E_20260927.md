# Three source-backed U.S. Code spans: local generation and Hub delivery

The actual three-document batch completed inventory, Parquet input creation, deterministic codec observation, typed compiler checks, Lake checks, and in-memory DuckDB readback. All **53 focused tests passed** with no failures, errors, or skips. The two output files were then uploaded to `justicedao/uscode-autoformal-span-cache` and downloaded from the returned immutable commit; exact bytes, three rows, all 48 evidence columns, and preservation of existing remote files were verified.

All three compiler outcomes remain **abstentions/gaps**, with `consensus=disagree`, `admitted=false`, and `formalized=false`. Successful Lake checks do not establish the statutes’ semantics.

| Retained source | Selected operative body and preserved qualification | Typed compiler gap |
|---|---|---|
| 7 U.S.C. § 2006d (`usc:us:7:2006d`) | Market placement program for qualified beginning farmers, ranchers, and specified borrowers; retains the guarantee “under this chapter.” | `UNSUPPORTED_SEMANTICS:cross_references` |
| 5 U.S.C. § 8410 (`usc:us:5:8410`) | Five years of creditable civilian service for annuity eligibility; retains the notwithstanding clause, § 8411 reference, and subchapter condition. | `UNSUPPORTED_SEMANTICS:overrides,cross_references,resolved_cross_references` |
| 16 U.S.C. § 6809 (`usc:us:16:6809`) | Authority terminates September 30, 2031; retains “this chapter” and original source spacing. | `UNSUPPORTED_SEMANTICS:cross_references` |

These are actual retained corpus rows, not synthetic demonstration spans. The input descriptor preserves full source texts and headings, exact selected UTF-8 body offsets/hashes, legal identifiers, entry CIDs, record hashes, original shard path/hash/row, and import receipt. The compiler consumed each selected source body directly, with no external vocabulary and `allow_partial=false`; it did not compile a simplified decoded substitute.

Source release: `justicedao/ipfs_uscode@5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`, release point `us/pl/119/102`, manifest SHA-256 `0c6c05582fda19f36c75b166c5c1afecdab156241ce73728f564802b52eacac6`. The three rows are 2, 53, and 52 of `data/corpus/part-000015.parquet`, SHA-256 `9a7693e41011a2e55cd7d31b15273cfbb5ec29ce900b7536df54c3ec5cc94cba`. Source authority and current official legal text were not independently authenticated; upstream retrieval claims remain distinct from the false legal-admission fields.

The Parquet uses `uscode-autoformal-span-evidence/v1`: 48 columns covering source identity/text, status and authority flags, compiler/decompiler results and gap fields, formula/citation/symbol/repair records, decoded/structural projections, losses and similarities, agreement/census observations, Lake disposition, and training disposition. The companion `uscode-autoformal-span-batch-provenance/v1` JSON retains the full decoded text, modal IR, raw metrics, complete compiler results, source provenance, source-code hashes/tree pin, Lake source/logs, and stage timings. Complete observations remain in the companion JSON where the row projection is abbreviated. In all three rows, `cross_entropy_loss`, `round_trip_cross_entropy_loss`, `formula_cross_entropy_loss`, and `view_cross_entropy_loss` are null: no typed decompiler alignment or bridge view was available. Family cross entropy, reconstruction, compression, and cosine measurements are present; missing measurements are not zero losses.

The codec was `DeterministicModalLogicCodec`, with FLogic disabled, actual spaCy `en_core_web_sm` (no fallback), stable mock source embeddings, and structural feature hashing for decoded embeddings. The installed spaCy pipeline handled parsing. No learned autoencoder checkpoint was evaluated or trained, no embedding provider was called, and no bridge or external prover evaluation ran. The direct codec path did not invoke the bridge metric cache. Earlier native checkpoint/model validation remains deferred.

Lake executed the existing `lake build Legal` path using installed `leanprover/lean4:v4.26.0`. All three commands returned zero. Their recorded scope is **“definitional modality/fingerprint boundary only”**; they do not override the compiler gaps or confer legal formalization/admission.

| Measured stage | Total for three spans | Arithmetic mean per span |
|---|---:|---:|
| Generation, including setup and output projection | 23.378234767 s | 7.792744922 s |
| Typed compiler | 0.752724677 s | 0.250908226 s |
| Direct codec observation | 7.587657156 s | 2.529219052 s |
| Lake checks | 6.598892203 s | 2.199630734 s |

These stage intervals are nested and must not be summed into a disjoint total. This is one small batch in a fresh generation process with new application objects; operating-system, filesystem, and library caches were uncontrolled, and input preparation/imports preceded generation timing. It is not an A/B benchmark, a cold-OS measurement, a full-corpus throughput estimate, or a bridge/legal-IR speed claim. The complete guarded local audit took 70.747780788 s, including tests and supervision.

The passing local run used one CPU, a 2,048 MiB memory limit, a 50 MB storage reservation, and a 600-second limit. Terminal child peak RSS was 810,336,256 bytes; final owned disk usage was 5,191,133 bytes. The child group was confirmed dead and reservation `f81db16061504c72adaa3c589ef435ae` was released after durable results. All 85 prior ledger records remained unchanged. Network access was denied during tests/generation; Hub publication ran separately under its own resource reservation.

The source guard covers imported canonical dataset modules, executed workspace Python, and explicitly pinned parser/compiler/decompiler and selected dependencies; it is **not** a whole-package qualification. The focused tests include the three-sentence compiler gate and empty-vocabulary abstention, temporal/minimum gates, symbol/meta-ontology behavior, codec exception preservation, evidence schema, mocked Lake behavior, and the source-batch CLI. In-memory DuckDB (`threads=1`) independently read the same generated Parquet and verified exact source IDs/text/hashes and false authority fields; no active corpus database was opened.

The first attempt is retained as failed evidence: its import guard incorrectly raised `RuntimeError` for a legitimately absent optional SMT module during pytest collection. No tests completed in that attempt. A fresh attempt changed the missing-module exception to `ModuleNotFoundError`, preserving canonical-tree refusal and leaving compiler/test semantics unchanged. Its failed 100 MB claim and receipts remain intact.

Before that first admission, concurrent Git synchronization had changed the inode of the same named evidence directory. Under the ledger lock, the owner refreshed only that root metadata, preserved all 84 then-existing records and the 62 GB cap, and verified both protected checkpoint hashes. The old ledger and root-identity repair receipt remain alongside the first attempt.

Local evidence (paths relative to the dataset repository):

- Passing audit, tests, child readback, and release: `workspace/test-logs/federal-corpus-audits/source-span-batch-3-20260927-r2/capture-r1/`.
- Complete generated evidence: that directory’s `outputs/span-evidence.parquet` and `outputs/span-evidence.provenance.json`; source descriptor/inventory/input are retained beside them.
- Failed initial attempt and root metadata refresh: `workspace/test-logs/federal-corpus-audits/source-span-batch-3-20260927/`.
- Actual upload and immutable readback: `workspace/test-logs/federal-corpus-audits/source-span-hub-publication-20260927/{publication,verification,audit,resource-release}.json`.

Published batch: `retained-source-operative-clauses-3-20260927`.

- Hub audited parent: `08289b3095d01efc1d36cc18b3bc2b19e482dc67`.
- Hub returned commit: `1960818abd1083c152ab3ba30f872d6677dcd154`.
- [Immutable Parquet](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/resolve/1960818abd1083c152ab3ba30f872d6677dcd154/autoformal/uscode/batches/retained-source-operative-clauses-3-20260927/span-evidence.parquet): 42,619 bytes, three rows.
- [Immutable provenance](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/resolve/1960818abd1083c152ab3ba30f872d6677dcd154/autoformal/uscode/batches/retained-source-operative-clauses-3-20260927/provenance.json): 4,142,976 bytes. The published provenance adds the validated code-commit/runtime context to the retained local provenance.
- Seven source/test changes published on dataset `origin/main`: `c09b48c6def0cb395912618e071002f1d4a96bdd`.

The upload added only this batch’s Parquet and full proof; exact returned-commit readback verified that existing files were preserved. The batch provides source-backed observations and compiler gaps. Legal admission and native training qualification remain false.
