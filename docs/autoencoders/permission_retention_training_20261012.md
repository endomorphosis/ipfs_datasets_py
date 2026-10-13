# LegalIR permission-retention training comparison

Both candidates are retained for engineering research. Neither is selected or promoted to a default decoder. The reference panels are previously exposed authored examples with shared templates, not independently reviewed US Code gold.

Each candidate starts from the same source-only 400-update parent, copies its weights, and receives 32 fresh Adam updates on the same 168 rows, batch size 12, learning rate 0.001 and seed/order 1729. The objective is identical: actor-ranking hinge disabled, presence CE weight 1, modality CE weight 2. Dimension 384 is configured but latent conditioning is disabled; no encoder executes.

The `all-parameters` arm trains all 23 named tensors. The `span-heads-only` arm trains six presence/start/end tensors and freezes 17 tensors, including byte embeddings, token projection, bidirectional source GRU, modality head and dormant latent branch. Its new checkpoint format stores genuine Adam moments for only its trainable subset. Existing checkpoint producers and single-source readout remain unchanged.

| Exposed authored panel | Parent raw / joint exact IR | All parameters | Span heads only |
| --- | ---: | ---: | ---: |
| Old regression, 96 rows | 96 / 96 | 93 / 93 | 96 / 96 |
| Fresh tuning, 36 rows | 0 / 0 | 6 / 15 | 0 / 1 |
| Fresh challenge, 36 rows | 7 / 7 | 23 / 23 | 8 / 8 |
| Earlier authored evaluation, 72 rows | 12 / 12 | 49 / 52 | 16 / 16 |
| Authored development, 72 rows | 0 / 0 | 40 / 42 | 4 / 4 |
| Newer authored evaluation, 72 rows | 6 / 6 | 19 / 22 | 6 / 6 |

All-parameter training reproduced all 392 saved source score payloads and raw/joint decisions from the preceding actor-OFF/presence-1 comparison. It introduced three permission-to-obligation errors on the old 96-row panel. The frozen arm preserved all 392 complete three-way modality vectors bit for bit, retained 96/96 old raw and joint outputs, and introduced no old permission-to-obligation errors. It met that necessary engineering retention gate, but did not improve the newer evaluation panel.

Freezing also preserves existing mistakes. On the newer panel's 24 permission references, the parent and frozen arm's heads predict P for 14, O for 4 and F for 6; the full-training arm predicts P for 2, O for 13 and F for 9. Raw and joint abstentions are reported separately in the analysis. Eight unreviewed law sources receive no targets or accuracy scores.

The release includes both opaque checkpoints, all 87 frozen result files, training and resource evidence, authored reference provenance, and reproducible sources. Both runs completed and released their reservations under the unchanged resource guardian. Pure checks passed 179 tests and 325 subtests. These results cover one parent, one schedule and one seed; they establish no statistical robustness, statutory semantic fidelity, genuine 8D/384D/768D latent decoding, broader logic-family correctness or `lake build legal` qualification.

The next architecture to test separates the frozen modality feature path from a trainable span feature path. It must preserve complete old outputs as well as permissions, and must be tested against independently reviewed statutory references before any promotion.
