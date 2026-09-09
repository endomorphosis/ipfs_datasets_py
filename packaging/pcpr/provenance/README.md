# PCPR-054 declared build provenance

These files bind source policy, tools, native dependencies, commands,
artifacts, and containers for the Datasets *release* profile. They are
not a signed SLSA/in-toto attestation and not a closed PCPR release.

- `cpython312/release.provenance.json` is the canonical declared
  binding.
- Exact git commit and tree are recorded on the PCPR-054 receipt
  `current_tree_binding` because nested admission rewrites HEAD.
- This document never pins `origin/main` as the release identity.
- Native z3/cvc5/lean/coqtop stay typed unavailable when absent from
  the sealed PATH.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
