# Authenticated decoder TRAIN-mixture comparison

Four matched decoder/projection-head fits complete 680 optimizer updates at 384D and 768D. The source encoders remain frozen and are not executed. Both arms preserve 48/48 original-development reconstruction; all 72 original control panels and 8 previously exposed wording panels are retained.

The 768D mixed arm lowers exposed-wording token cross-entropy by 14.34% with 46/48 exact paragraphs in both arms. The 384D mixed arm regresses from 20/48 to 18/48 despite slightly lower sequence loss. No production checkpoint or default is promoted. These are restricted authored-rule experiments, not fresh statutory holdouts or all-family qualification.

See results.json for numerical metrics, timing scopes and artifact identities, and docs/autoencoders/four_width_training.md for the implementation and run interface. The ordered split gzip archive contains full reports, predictions, small trained head states, schedules, frozen extensions, guards, tests, development failures and reviews. Concatenate parts in manifest order and verify their hashes before reading the tar stream. Every original path is mapped to an archive member; byte-identical files share a member. The prior published manifest supplies unchanged transitive dependencies. External pretrained model weights and native binaries are excluded.

Temperature 0; context/output 512; cached native vectors; no downloads. 8D linguistic teacher and 4096D endpoints unchanged. No legal-IR bridge timing, speedup, convergence, global minimum, formalization, roundtrip_ok, proof authority or Lean admission is claimed. Only an actual lake build <Lib> can grant Lean admission. The Constitution remains unformalized.
