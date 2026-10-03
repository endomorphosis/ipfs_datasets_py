# Retained AST SQL diagnostic

This is an external SQL-only diagnostic, not a benchmark score or a Source384 qualification. No production source was changed. No model, provider, training, source execution, or hidden verifier was used.

The final read-only export binds the successful native full-context-04 receipt to its actual `codebase_control.heads` row and the unchanged source database bytes. It exports the original canonical 31 AST projection inputs and full row digests/counts for the 13 catalog tables. The locally retained 9,412,206-byte corpus has SHA256 `cd84435f534cfcd29b4e4ef5928542d57e630529c0d86eba34baa1b1c02966bd`. Do not copy its task AST payload into an eventual public evidence package; retain the digest and reproduction recipe.

The final harness SHA256 is `181ca8064c9529514f68bee2e87c6cae4d67862ab63082a92d1eea3b61878671`; `final-pins.json` records the complete local selection. The alternative is the external reviewed `vector_candidate.py` with SHA256 `be404be397941857bc21f2b99af2240a29a4dc7944018bd6a1f72ce70736b72c`. It retains the native 128-row / 256-KiB chunk policy, lazy input consumption, nine fact families, transaction scope, and oversized-row behavior.

Twelve final tiny controls passed in 2.08 seconds (`tiny-05.xml`), including stale generation and foreign manifest export refusal without database modification. Earlier test sources, logs and the failed real export are retained separately: the diagnostic originally omitted the native head envelope's schema field, which the actual export refused. This was corrected before the paired replay. `initial-corpus.json` is an earlier export without the head-row check and was not used for the final pair.

Both paired host replays use fresh databases and the same corpus, native producer, one DuckDB thread, 512 MB connection limit, 90-second diagnostic deadline, and capped numerical library threads. DuckDB 1.5.5 / Python 3.12.3 / aarch64 and the exact engine binary hash, filesystem, settings and resource counters are recorded in each receipt. The process runs the native canonical reconstruction and `apply_batch`; only the candidate insertion hook is temporarily replaced, and it is restored in `finally`. Both passes verified every row digest/count and a cold native canonical reopen. Native execute timing includes parameter binding and excludes telemetry preparation and cursor fetching. The inclusive insertion-family timer includes instrumentation overhead.

| Single ordered host run | VALUES baseline | Column-list UNNEST candidate |
| --- | ---: | ---: |
| apply_batch seconds | 4.664 | 2.135 |
| summed execute seconds | 3.399 | 0.946 |
| summed insertion-family seconds | 3.179 | 0.768 |
| total diagnostic seconds | 8.828 | 6.133 |
| execute calls | 1,132 | 1,132 |
| scalar values | 870,877 | 870,877 |
| bound parameters | 870,877 | 10,816 |

`host-pair-comparison.json` binds the two receipts. This single host comparison does not establish Docker performance or an end-to-end speedup. The Docker launcher and its admission remain owned by the root agent. Neither the native 90-second Source384 deadline nor its production resource policy was modified.
