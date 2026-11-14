# Preserved incompatible counterexample-envelope source

This branch retains two exact authored owner variants and their baseline generic API test. It is a preservation branch, not a current-main migration or qualification. No variant-specific test was supplied or executed.

Both variants use an `@2` interface label, but their wire schemas, required identity fields and retention semantics differ. The preserved API can accept caller authority above the maintained bounded ceiling and the preserved normalizer has a weaker fallback. Do not introduce an alias or replace main with this version.

A future port must keep main's strict wire validation, source/assumption identity, mandatory normalizer, explicit retention constraints and bounded authority ceiling. It needs adversarial tests for forged digests, schema swaps, hidden private paths, missing normalizers, conflicting authorities and lossy source-map conversion. Source-map conveniences may only extend the existing owner after those checks.

Use the maintained main branch for current behavior. These preserved source bytes establish no proof, trust, legal or runtime authority.
